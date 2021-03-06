# Copyright (c) 2019 SAP SE or an SAP affiliate company. All rights reserved. This file is licensed
# under the Apache Software License, v. 2 except as noted otherwise in the LICENSE file
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import pathlib
import shutil
import sys
import yaml

import termcolor

from urllib.parse import urlunparse


class Failure(RuntimeError, ValueError):
    pass


def _set_cli(is_cli: bool):
    ctx().args._cli = is_cli
    global Failure
    if is_cli:
        class Failure(SystemExit):
            pass
    else:
        class Failure(RuntimeError):
            pass


def existing_file(path):
    if isinstance(path, pathlib.Path):
        is_file = path.is_file()
    else:
        is_file = os.path.isfile(path)
    if not is_file:
        fail('not an existing file: ' + str(path))
    return path


def existing_dir(path: str):
    if isinstance(path, pathlib.Path):
        is_dir = path.is_dir()
    else:
        is_dir = os.path.isdir(path)
    if not is_dir:
        fail('not an existing directory: ' + str(path))
    return path


def check_type(instance, type):
    if not isinstance(instance, type):
        fail('{i} is not an instance of {t}'.format(i=instance, t=type))
    return instance


class CliHint(object):
    def __init__(self, typehint=str, *args, **kwargs):
        self.argparse_args = dict(*args, **kwargs)
        self.typehint = typehint


class CliHints(object):
    '''
    predefined cli hint instances
    '''
    @staticmethod
    def existing_file(help: str='an existing file', **kwargs):
        return CliHint(type=existing_file, help=help, **kwargs)

    @staticmethod
    def yaml_file(help: str='an existing YAML file', **kwargs):
        return CliHint(type=parse_yaml_file, help=help, **kwargs)

    @staticmethod
    def existing_dir(help: str='an existing directory', **kwargs):
        return CliHint(type=existing_dir, help=help, **kwargs)

    @staticmethod
    def non_empty_string(help:str = 'a non-empty string', **kwargs):
        return CliHint(type=not_empty, help=help, **kwargs)


def ctx():
    # late import because the ctx module is altered after all existing modules have
    # already been imported
    import ctx
    return ctx


def _quiet():
    return ctx().args and ctx().args.quiet


def _verbose():
    return ctx().args and ctx().args.verbose


def _cli():
    return bool(ctx().args and hasattr(ctx().args, '._cli') and ctx().args._cli)


def _print(msg, colour):
    if not msg:
        return
    if not sys.stdout.isatty():
        sys.stdout.write(msg + '\n')
    else:
        sys.stdout.write(termcolor.colored(msg, colour) + '\n')

    sys.stdout.flush()


def error(msg=None):
    if _quiet():
        return
    if msg:
        _print('ERROR: ' + str(msg), colour='red')


def fail(msg=None):
    if msg:
        _print('ERROR: ' + str(msg), colour='red')
    raise Failure(1)


def info(msg:str):
    if _quiet():
        return
    if msg:
        _print('INFO: ' + str(msg), colour='cyan')


def warning(msg:str):
    if _quiet():
        return
    if msg:
        _print('WARNING: ' + str(msg), 'red')


def verbose(msg:str):
    if not _verbose():
        return
    if msg:
        _print('VERBOSE: ' + msg, colour=None)


def success(msg:str):
    if msg:
        _print('SUCCESS: ' + msg, colour='green')


def not_empty(value):
    if not value or len(value) == 0:
        fail('passed value must not be empty')
    return value


def not_none(value):
    if value is None:
        fail('passed value must not be None')
    return value


def none(value):
    if value is not None:
        fail('value must be None')
    return value


def is_yaml_file(path: CliHints.existing_file()):
    with open(path) as f:
        try:
            if yaml.load(f):
                return True
        except Exception:
            warning('an error occurred whilst trying to parse {f}'.format(f=path))
            raise
    return False


def parse_yaml_file(path: CliHints.existing_file()):
    with open(path) as f:
            return yaml.load(f)


def random_str(prefix=None, length=12):
    import random
    import string
    if prefix:
        length -= len(prefix)
    else:
        prefix = ''
    return prefix + ''.join(random.choice(string.ascii_lowercase) for _ in range(length))


def create_url_from_attributes(
    netloc: str,
    scheme='https',
    path='',
    params='',
    query='',
    fragment=''
):
    return urlunparse((scheme, netloc, path, params, query, fragment))


def check_env(name: str):
    '''
    returns: the specified environment variable's value.
    raises: util.Failure if no environment variable with the given name is defined
    '''
    not_none(name)
    if name in os.environ:
        return os.environ[name]
    fail('env var {n} must be set'.format(n=name))


def _running_on_ci():
    '''
    heuristically determines whether or not the caller is running inside a central
    CI/CD job.
    '''
    return 'CC_ROOT_DIR' in os.environ


def _root_dir():
    if not _running_on_ci():
        raise RuntimeError('must only be called within CI/CD')
    return check_env('CC_ROOT_DIR')


def urljoin(*parts):
    if len(parts) == 1:
        return parts[0]
    first = parts[0]
    last = parts[-1]
    middle = parts[1:-1]

    first = first.rstrip('/')
    middle = list(map(lambda s: s.strip('/'), middle))
    last = last.lstrip('/')

    return '/'.join([first] + middle + [last])


def which(cmd_name: str) -> str:
    '''
    wrapper around shutil.which that calls util.fail if the requested executable is not
    found in the PATH.
    '''
    cmd_path = shutil.which(cmd_name)
    if not cmd_path:
        fail("{cmd} not found in PATH".format(cmd=cmd_name))
    return cmd_path


def merge_dicts(base: dict, other: dict, list_semantics='merge'):
    '''
    merges copies of the given dict instances and returns the merge result.
    The arguments remain unmodified. However, it must be possible to copy them
    using `copy.deepcopy`.

    Merging is done using the `deepmerge` module. In case of merge conflicts, values from
    `other` overwrite values from `base`.

    By default, different from the original implementation, a merge will be applied to
    lists. This results in deduplication retaining element order. The elements from `other` are
    appended to those from `base`.

    '''
    not_none(base)
    not_none(other)

    from deepmerge import Merger

    if list_semantics == 'merge':
        # monkey-patch merge-strategy for lists
        list_merge_strategy = Merger.PROVIDED_TYPE_STRATEGIES[list]
        list_merge_strategy.strategy_merge = lambda c, p, base, other: \
            list(base) + [e for e in other if e not in base]

        strategy_cfg = [(list, ['merge']), (dict, ['merge'])]
        merger = Merger(strategy_cfg, ['override'], ['override'])
    elif list_semantics is None:
        strategy_cfg = [(dict, ['merge'])]
        merger = Merger(strategy_cfg, ['override'], ['override'])
    else:
        raise NotImplementedError

    from copy import deepcopy
    # copy dicts, so they remain unmodified
    return merger.merge(deepcopy(base), deepcopy(other))


class FluentIterable(object):
    ''' a fluent object stream processing chain builder inspired by guava's FluentIterable

    Example:
        result = FluentIterable(items=(1,2,3))
            .filter(lambda e: e < 2)
            .map(lambda e: e * 2)
            .as_generator()

    '''

    def __init__(self, items):
        def starter():
            yield from items
        self.ops = [starter]

    def filter(self, filter_func):
        last_op = self.ops[-1]

        def f():
            yield from filter(filter_func, last_op())

        self.ops.append(f)
        return self

    def map(self, map_func):
        last_op = self.ops[-1]

        def m():
            yield from map(map_func, last_op())

        self.ops.append(m)
        return self

    def as_generator(self):
        return self.ops[-1]()

    def as_list(self):
        return list(self.as_generator())
