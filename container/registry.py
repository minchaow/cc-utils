# Copyright 2017 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""This package pulls images from a Docker Registry."""


import functools
import tarfile
import tempfile

import util
from model.container_registry import Privileges

from containerregistry.client import docker_creds
from containerregistry.client import docker_name
from containerregistry.client.v2 import docker_image as v2_image
from containerregistry.client.v2_2 import docker_http
from containerregistry.client.v2_2 import docker_image as v2_2_image
from containerregistry.client.v2_2 import docker_image_list as image_list
from containerregistry.client.v2_2 import docker_session
from containerregistry.client.v2_2 import save
from containerregistry.client.v2_2 import v2_compat
from containerregistry.transport import retry
from containerregistry.transport import transport_pool

import httplib2


_DEFAULT_TAG = 'i-was-a-digest'

_PROCESSOR_ARCHITECTURE = 'amd64'

_OPERATING_SYSTEM = 'linux'


# Today save.tarball expects a tag, which is emitted into one or more files
# in the resulting tarball.  If we don't translate the digest into a tag then
# the tarball format leaves us no good way to represent this information and
# folks are left having to tag the resulting image ID (yuck).  As a datapoint
# `docker save -o /tmp/foo.tar bar@sha256:deadbeef` omits the v1 "repositories"
# file and emits `null` for the `RepoTags` key in "manifest.json".  By doing
# this we leave a trivial breadcrumb of what the image was named (and the digest
# is recoverable once the image is loaded), which is a strictly better UX IMO.
# We do not need to worry about collisions by doing this here because this tool
# only packages a single image, so this is preferable to doing something similar
# in save.py itself.
def _make_tag_if_digest(
    name):
  if isinstance(name, docker_name.Tag):
    return name
  return docker_name.Tag('{repo}:{tag}'.format(
      repo=str(name.as_repository()), tag=_DEFAULT_TAG))


def normalise_image_reference(image_reference):
  util.check_type(image_reference, str)
  if '@' in image_reference:
    return image_reference

  parts = image_reference.split('/')

  left_part = parts[0]
  # heuristically check if we have a (potentially) valid hostname
  if '.' not in left_part.split(':')[0]:
    # insert 'library' if only image name was given
    if len(parts) == 1:
      parts.insert(0, 'library')

    # probably, the first part is not a hostname; inject default registry host
    parts.insert(0, 'registry-1.docker.io')

  return '/'.join(parts)


def _parse_image_reference(image_reference):
  util.check_type(image_reference, str)

  if '@' in image_reference:
    name = docker_name.Digest(image_reference)
  else:
    name = docker_name.Tag(image_reference)

  return name


@functools.lru_cache()
def _credentials(image_reference: str, privileges:Privileges=None):
    util.check_type(image_reference, str)

    cfg_factory = util.ctx().cfg_factory()

    matching_cfgs = [
        cfg for cfg in
        cfg_factory._cfg_elements('container_registry')
        if cfg.image_ref_matches(image_reference, privileges=privileges)
    ]

    if not matching_cfgs:
        return None

    # use first match
    credentials = matching_cfgs[0].credentials()

    return docker_creds.Basic(username=credentials.username(), password=credentials.passwd())


def retrieve_container_image(image_reference: str, outfileobj=None):
  tmp_file = _pull_image(image_reference=image_reference, outfileobj=outfileobj)
  tmp_file.seek(0)
  return tmp_file


def publish_container_image(image_reference: str, image_file_obj):
  image_file_obj.seek(0)
  _push_image(image_reference=image_reference, image_file=image_file_obj.name)
  image_file_obj.seek(0)


def _mk_transport():
  retry_factory = retry.Factory()
  retry_factory = retry_factory.WithSourceTransportCallable(httplib2.Http)
  transport = transport_pool.Http(retry_factory.Build, size=8)
  return transport


def _push_image(image_reference: str, image_file: str, threads=8):
  import util
  util.not_none(image_reference)
  util.existing_file(image_file)

  transport = _mk_transport()

  image_reference = normalise_image_reference(image_reference)
  name = _parse_image_reference(image_reference)

  try:
    # first try container_registry cfgs from available cfg
    creds = _credentials(image_reference=image_reference, privileges=Privileges.READ_WRITE)
    if not creds:
      print('could not find rw-creds')
      # fall-back to default docker lookup
      creds = docker_creds.DefaultKeychain.Resolve(name)
  except Exception as e:
    util.fail('Error resolving credentials for {name}: {e}'.format(name=name, e=e))

  with v2_2_image.FromTarball(image_file) as v2_2_img:
    try:
      with docker_session.Push(
          name,
          creds,
          transport,
          threads=threads,
      ) as session:
        session.upload(v2_2_img)
        digest = v2_2_img.digest()
        print(f'{name} was uploaded - digest: {digest}')
    except Exception as e:
      import traceback
      traceback.print_exc()
      raise e


def _pull_image(image_reference: str, outfileobj=None):
  import util
  util.not_none(image_reference)

  transport = _mk_transport()

  image_reference = normalise_image_reference(image_reference)
  name = _parse_image_reference(image_reference)

  # OCI Image Manifest is compatible with Docker Image Manifest Version 2,
  # Schema 2. We indicate support for both formats by passing both media types
  # as 'Accept' headers.
  #
  # For reference:
  #   OCI: https://github.com/opencontainers/image-spec
  #   Docker: https://docs.docker.com/registry/spec/manifest-v2-2/
  accept = docker_http.SUPPORTED_MANIFEST_MIMES

  # Resolve the appropriate credential to use based on the standard Docker
  # client logic.
  try:
    # first try container_registry cfgs from available cfg
    creds = _credentials(image_reference=image_reference)
    if not creds:
      # fall-back to default docker lookup
      creds = docker_creds.DefaultKeychain.Resolve(name)
  except Exception as e:
    util.fail('Error resolving credentials for {name}: {e}'.format(name=name, e=e))

  try:
    # XXX TODO: use streaming rather than writing to local FS
    # if outfile is given, we must use it instead of an ano
    outfileobj = outfileobj if outfileobj else tempfile.TemporaryFile()
    with tarfile.open(fileobj=outfileobj, mode='w:') as tar:
      util.verbose('Pulling manifest list from {name}..'.format(name=name))
      with image_list.FromRegistry(name, creds, transport) as img_list:
        if img_list.exists():
          platform = image_list.Platform({
              'architecture': _PROCESSOR_ARCHITECTURE,
              'os': _OPERATING_SYSTEM,
          })
          # pytype: disable=wrong-arg-types
          with img_list.resolve(platform) as default_child:
            save.tarball(_make_tag_if_digest(name), default_child, tar)
            return outfileobj
          # pytype: enable=wrong-arg-types

      util.info('Pulling v2.2 image from {name}..'.format(name=name))
      with v2_2_image.FromRegistry(name, creds, transport, accept) as v2_2_img:
        if v2_2_img.exists():
          save.tarball(_make_tag_if_digest(name), v2_2_img, tar)
          return outfileobj

      util.info('Pulling v2 image from {name}..'.format(name=name))
      with v2_image.FromRegistry(name, creds, transport) as v2_img:
        with v2_compat.V22FromV2(v2_img) as v2_2_img:
          save.tarball(_make_tag_if_digest(name), v2_2_img, tar)
          return outfileobj
  except Exception as e:
    outfileobj.close()
    util.fail('Error pulling and saving image {name}: {e}'.format(name=name, e=e))
