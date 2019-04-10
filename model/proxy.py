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

from model.base import (
    ModelBase,
)


class DockerImageConfig(ModelBase):
    def _required_attributes(self):
            return super._required_attributes() + [
                'image_name',
                'image_tag',
            ]

    def image_name(self):
        return self.raw['image_name']

    def image_tag(self):
        return self.raw['image_tag']


class ProxyConfig(ModelBase):
    def _required_attributes(self):
            return super._required_attributes() + [
                'mitm_proxy',
                'setup_iptables',
            ]

    def mitm_proxy(self):
        return MitmProxyConfig(raw_dict=self.raw['mitm_proxy'])

    def setup_iptables(self):
        return DockerImageConfig(raw_dict=self.raw['setup_iptables'])


class MitmProxyConfig(DockerImageConfig):
    def _required_attributes(self):
        return super._required_attributes() + ['config']

    def config(self):
        return self.raw['config']
