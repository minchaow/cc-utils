# Copyright (c) 2018 SAP SE or an SAP affiliate company. All rights reserved. This file is licensed under the Apache Software License, v. 2 except as noted otherwise in the LICENSE file
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
from functools import partial

from protecode.client import ProtecodeApi
from protecode.model import ProcessingStatus
from util import not_none, warning
from container.image import retrieve_container_image
from .model import ContainerImage, Component, UploadResult, UploadStatus


class ProtecodeUtil(object):
    def __init__(self, protecode_api: ProtecodeApi, group_id=None):
        self._api = not_none(protecode_api)
        self._group_id = group_id

    def _image_ref_metadata(self, container_image):
        return {'image-reference': container_image.image_reference()}

    def _component_metadata(self, component):
        return {
            'component-name': component.name(),
            'component-version': component.version(),
        }

    def _upload_name(self, container_image, component):
        return '{c}_{i}_{v}'.format(
            c=component.name(),
            i=container_image.name(),
            v=container_image.version(),
        )

    def _metadata(self, container_image: ContainerImage, component: Component):
        metadata = self._image_ref_metadata(container_image)
        metadata.update(self._component_metadata(component))
        return metadata

    def retrieve_scan_result(
            self,
            container_image: ContainerImage,
            component: Component,
            full_result: bool=True,
        ):
        metadata = self._metadata(container_image=container_image, component=component)
        existing_products = self._api.list_apps(
            group_id=self._group_id,
            custom_attribs=metadata
        )
        if len(existing_products) > 0:
            if len(existing_products) > 1:
                warning('found more than one product for image {i}'.format(i=container_image))
            # use first (or only) match (we already printed a warning if we found more than one)
            product =  existing_products[0]
            if not full_result:
                return product
            return self._api.scan_result(product_id=product.product_id())

    def upload_image(
            self,
            container_image: ContainerImage,
            component: Component,
            wait_for_result: bool=False
        ):
        metadata = self._metadata(container_image=container_image, component=component)

        upload_result = partial(UploadResult, container_image=container_image, component=component)

        # check if the image has already been uploaded for this component
        scan_result = self.retrieve_scan_result(
            container_image=container_image,
            component=component,
        )

        if scan_result:
            return upload_result(
                status=UploadStatus.SKIPPED_ALREADY_EXISTED,
                result=scan_result,
            )

        # image was not yet uploaded - do this now
        image_data = retrieve_container_image(container_image.image_reference())
        result = self._api.upload(
            application_name=self._upload_name(container_image=container_image, component=component),
            group_id=self._group_id,
            data=image_data.stream(),
            custom_attribs=metadata,
        )

        if wait_for_result:
            result = self._api.wait_for_scan_result(product_id=result.product_id())

        if result.status() == ProcessingStatus.BUSY:
            upload_status = UploadStatus.UPLOADED_PENDING
        else:
            upload_status = UploadStatus.UPLOADED_DONE

        return upload_result(
            status=upload_status,
            result=result
        )
