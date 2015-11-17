# Copyright (c) 2015 Orange.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import contextlib
import copy
import mock
import webob.exc

from oslo_utils import uuidutils

from neutron.api import extensions as api_extensions
from neutron.db import servicetype_db as sdb
from neutron.tests.unit.db import test_db_base_plugin_v2

from networking_bgpvpn.neutron.db import bgpvpn_db
from networking_bgpvpn.neutron import extensions
from networking_bgpvpn.neutron.services.common import constants
from networking_bgpvpn.neutron.services import plugin
from networking_bgpvpn.neutron.services.service_drivers import driver_api

_uuid = uuidutils.generate_uuid


class BgpvpnTestCaseMixin(test_db_base_plugin_v2.NeutronDbPluginV2TestCase):

    def setUp(self, service_provider=None):
        if not service_provider:
            provider = (constants.BGPVPN +
                        ':dummy:networking_bgpvpn.neutron.services.'
                        'service_drivers.driver_api.BGPVPNDriver:default')
        else:
            provider = (constants.BGPVPN + ':test:' + service_provider +
                        ':default')

        bits = provider.split(':')
        provider = {
            'service_type': bits[0],
            'name': bits[1],
            'driver': bits[2]
        }
        if len(bits) == 4:
            provider['default'] = True
        # override the default service provider
        self.service_providers = (
            mock.patch.object(sdb.ServiceTypeManager,
                              'get_service_providers').start())
        self.service_providers.return_value = [provider]

        bgpvpn_plugin_str = ('networking_bgpvpn.neutron.services.plugin.'
                             'BGPVPNPlugin')
        service_plugins = {'bgpvpn_plugin': bgpvpn_plugin_str}

        self.bgpvpn_plugin = plugin.BGPVPNPlugin()
        extensions_path = ':'.join(extensions.__path__)
        ext_mgr = api_extensions.PluginAwareExtensionManager(
            extensions_path,
            {constants.BGPVPN: self.bgpvpn_plugin})

        super(BgpvpnTestCaseMixin, self).setUp(
            service_plugins=service_plugins,
            ext_mgr=ext_mgr)

        self.bgpvpn_data = {'bgpvpn': {'name': 'bgpvpn1',
                                       'type': 'l3',
                                       'route_targets': ['1234:56'],
                                       'auto_aggregate': False,
                                       'tenant_id': self._tenant_id}}
        self.converted_data = copy.copy(self.bgpvpn_data)
        self.converted_data['bgpvpn'].update({'export_targets': [],
                                              'import_targets': [],
                                              'route_distinguishers': []})

    @contextlib.contextmanager
    def bgpvpn(self, do_delete=True, **kwargs):
        fmt = 'json'
        tenant_id = kwargs.get('tenant_id') if 'tenant_id' in kwargs\
            else self._tenant_id
        if(kwargs.get('data')):
            bgpvpn_data = kwargs.get('data')
        else:
            bgpvpn_data = {'bgpvpn': {'name': 'bgpvpn1',
                                      'type': 'l3',
                                      'route_targets': ['1234:56'],
                                      'auto_aggregate': False,
                                      'tenant_id': tenant_id}}
        bgpvpn_req = self.new_create_request(
            'bgpvpn/bgpvpns', bgpvpn_data, fmt=fmt)
        res = bgpvpn_req.get_response(self.ext_api)
        if res.status_int >= 400:
            raise webob.exc.HTTPClientError(code=res.status_int)
        bgpvpn = self.deserialize('json', res)
        yield bgpvpn
        if do_delete:
            self._delete('bgpvpn/bgpvpns',
                         bgpvpn['bgpvpn']['id'])

    @contextlib.contextmanager
    def assoc_net(self, bgpvpn_id, net_id, do_disassociate=True):
        fmt = 'json'
        data = {'network_association': {'network_id': net_id,
                                        'tenant_id': self._tenant_id}}
#         data = {'network_association': {'network_id': net_id}}
        bgpvpn_net_req = self.new_create_request(
            'bgpvpn/bgpvpns',
            data=data,
            fmt=fmt,
            id=bgpvpn_id,
            subresource='network_associations')
        res = bgpvpn_net_req.get_response(self.ext_api)
        if res.status_int >= 400:
            raise webob.exc.HTTPClientError(code=res.status_int)
        assoc = self.deserialize('json', res)
        yield assoc
        if do_disassociate:
            del_req = self.new_delete_request(
                'bgpvpn/bgpvpns',
                bgpvpn_id,
                fmt=self.fmt,
                subresource='network_associations',
                sub_id=assoc['network_association']['id'])
            res = del_req.get_response(self.ext_api)
            if res.status_int >= 400:
                raise webob.exc.HTTPClientError(code=res.status_int)


class TestBGPVPNServicePlugin(BgpvpnTestCaseMixin):

    def setUp(self):
        super(TestBGPVPNServicePlugin, self).setUp()

    @mock.patch.object(plugin.BGPVPNPlugin, '_validate_network')
    def test_bgpvpn_net_assoc_create(self, mock_validate):
        with self.network() as net:
            net_id = net['network']['id']
            with self.bgpvpn() as bgpvpn:
                id = bgpvpn['bgpvpn']['id']
                mock_validate.return_value = net['network']
                with self.assoc_net(id, net_id):
                    net_body = {'network_id': net['network']['id'],
                                'tenant_id': self._tenant_id}
                    mock_validate.assert_called_once_with(mock.ANY,
                                                          net_body)

    def test_associate_empty_network(self):
        with self.bgpvpn() as bgpvpn:
            id = bgpvpn['bgpvpn']['id']
            data = {}
            bgpvpn_net_req = self.new_create_request(
                'bgpvpn/bgpvpns',
                data=data,
                fmt=self.fmt,
                id=id,
                subresource='network_associations')
            res = bgpvpn_net_req.get_response(self.ext_api)
            self.assertEqual(res.status_int, webob.exc.HTTPBadRequest.code)

    def test_associate_unknown_network(self):
        with self.bgpvpn() as bgpvpn:
            id = bgpvpn['bgpvpn']['id']
            net_id = _uuid()
            data = {'network_association': {'network_id': net_id,
                                            'tenant_id': self._tenant_id}}
            bgpvpn_net_req = self.new_create_request(
                'bgpvpn/bgpvpns',
                data=data,
                fmt=self.fmt,
                id=id,
                subresource='network_associations')
            res = bgpvpn_net_req.get_response(self.ext_api)
            self.assertEqual(res.status_int, webob.exc.HTTPNotFound.code)

    def test_associate_unauthorized_net(self):
        with self.network() as net:
            net_id = net['network']['id']
            with self.bgpvpn(tenant_id='another_tenant') as bgpvpn:
                id = bgpvpn['bgpvpn']['id']
                data = {'network_association': {'network_id': net_id,
                                                'tenant_id': self._tenant_id}}
                bgpvpn_net_req = self.new_create_request(
                    'bgpvpn/bgpvpns',
                    data=data,
                    fmt=self.fmt,
                    id=id,
                    subresource='network_associations')
                res = bgpvpn_net_req.get_response(self.ext_api)
                self.assertEqual(res.status_int, webob.exc.HTTPForbidden.code)

    def test_net_assoc_belong_to_diff_tenant(self):
        with self.network() as net:
            net_id = net['network']['id']
            with self.bgpvpn() as bgpvpn:
                id = bgpvpn['bgpvpn']['id']
                data = {'network_association': {'network_id': net_id,
                                                'tenant_id': 'another_tenant'}}
                bgpvpn_net_req = self.new_create_request(
                    'bgpvpn/bgpvpns',
                    data=data,
                    fmt=self.fmt,
                    id=id,
                    subresource='network_associations')
                res = bgpvpn_net_req.get_response(self.ext_api)
                self.assertEqual(res.status_int, webob.exc.HTTPForbidden.code)


class TestBGPVPNServiceDriverDB(BgpvpnTestCaseMixin):

    def setUp(self):
        super(TestBGPVPNServiceDriverDB, self).setUp()

    @mock.patch.object(driver_api.BGPVPNDriver,
                       'create_bgpvpn_postcommit')
    @mock.patch.object(bgpvpn_db.BGPVPNPluginDb, 'create_bgpvpn')
    def test_create_bgpvpn(self, mock_create_db, mock_create_postcommit):
        mock_create_db.return_value = self.converted_data['bgpvpn']
        with self.bgpvpn(do_delete=False):
            mock_create_db.assert_called_once_with(
                mock.ANY, self.converted_data['bgpvpn'])
            mock_create_postcommit.assert_called_once_with(
                mock.ANY, self.converted_data['bgpvpn'])

    @mock.patch.object(driver_api.BGPVPNDriver,
                       'delete_bgpvpn_postcommit')
    def test_delete_bgpvpn(self, mock_delete_postcommit):
        with self.bgpvpn(do_delete=False) as bgpvpn:
            patcher = mock.patch.object(bgpvpn_db.BGPVPNPluginDb,
                                        'delete_bgpvpn',
                                        return_value=self.converted_data)
            mock_delete_db = patcher.start()

            self._delete('bgpvpn/bgpvpns',
                         bgpvpn['bgpvpn']['id'])
            mock_delete_db.assert_called_once_with(mock.ANY,
                                                   bgpvpn['bgpvpn']['id'])
            mock_delete_postcommit.assert_called_once_with(mock.ANY,
                                                           self.converted_data)
            patcher.stop()
            self._delete('bgpvpn/bgpvpns',
                         bgpvpn['bgpvpn']['id'])

    @mock.patch.object(bgpvpn_db.BGPVPNPluginDb, 'get_bgpvpn')
    def test_get_bgpvpn(self, mock_get_db):
        with self.bgpvpn() as bgpvpn:
            self._show('bgpvpn/bgpvpns', bgpvpn['bgpvpn']['id'])
            mock_get_db.assert_called_once_with(mock.ANY,
                                                bgpvpn['bgpvpn']['id'],
                                                mock.ANY)

    def test_get_bgpvpn_with_net(self):
        with self.network() as net:
            net_id = net['network']['id']
            with self.bgpvpn() as bgpvpn:
                with self.assoc_net(bgpvpn['bgpvpn']['id'], net_id=net_id):
                    res = self._show('bgpvpn/bgpvpns', bgpvpn['bgpvpn']['id'])
                    self.assertIn('networks', res['bgpvpn'])
                    self.assertEqual(net_id,
                                     res['bgpvpn']['networks'][0])

    @mock.patch.object(driver_api.BGPVPNDriver,
                       'update_bgpvpn_postcommit')
    @mock.patch.object(bgpvpn_db.BGPVPNPluginDb,
                       'update_bgpvpn')
    def test_update_bgpvpn(self, mock_update_db, mock_update_postcommit):
        with self.bgpvpn() as bgpvpn:
            new_data = {"bgpvpn": {"name": "foo"}}
            old_bgpvpn = copy.copy(self.bgpvpn_data['bgpvpn'])
            old_bgpvpn['id'] = bgpvpn['bgpvpn']['id']
            old_bgpvpn['networks'] = []
            new_bgpvpn = copy.copy(old_bgpvpn)
            new_bgpvpn['name'] = 'foo'

            mock_update_db.return_value = new_bgpvpn

            self._update('bgpvpn/bgpvpns',
                         bgpvpn['bgpvpn']['id'],
                         new_data)

            mock_update_db.assert_called_once_with(
                mock.ANY, bgpvpn['bgpvpn']['id'], new_data['bgpvpn'])
            mock_update_postcommit.assert_called_once_with(
                mock.ANY, old_bgpvpn, new_bgpvpn)

    @mock.patch.object(driver_api.BGPVPNDriver,
                       'create_net_assoc_postcommit')
    @mock.patch.object(bgpvpn_db.BGPVPNPluginDb, 'create_net_assoc')
    def test_create_bgpvpn_net_assoc(self, mock_db_create_assoc,
                                     mock_post_commit):
        with self.bgpvpn() as bgpvpn:
            bgpvpn_id = bgpvpn['bgpvpn']['id']
            with self.network() as net:
                net_id = net['network']['id']
                assoc_id = _uuid()
                data = {'tenant_id': self._tenant_id,
                        'network_id': net_id}
                net_assoc_dict = copy.copy(data)
                net_assoc_dict.update({'id': assoc_id,
                                       'bgpvpn_id': bgpvpn_id})
                mock_db_create_assoc.return_value = net_assoc_dict
                with self.assoc_net(bgpvpn_id, net_id=net_id,
                                    do_disassociate=False):
                    mock_db_create_assoc.assert_called_once_with(
                        mock.ANY, bgpvpn_id, data)
                    mock_post_commit.assert_called_once_with(mock.ANY,
                                                             net_assoc_dict)

    @mock.patch.object(bgpvpn_db.BGPVPNPluginDb, 'get_net_assoc')
    def test_get_bgpvpn_net_assoc(self, mock_get_db):
        with self.bgpvpn() as bgpvpn:
            bgpvpn_id = bgpvpn['bgpvpn']['id']
            with self.network() as net:
                net_id = net['network']['id']
                with self.assoc_net(bgpvpn_id, net_id=net_id) as assoc:
                    assoc_id = assoc['network_association']['id']
                    res = 'bgpvpn/bgpvpns/' + bgpvpn_id + \
                          '/network_associations'
                    self._show(res, assoc_id)
                    mock_get_db.assert_called_once_with(mock.ANY,
                                                        assoc_id,
                                                        bgpvpn_id,
                                                        [])

    @mock.patch.object(bgpvpn_db.BGPVPNPluginDb, 'get_net_assocs')
    def test_get_bgpvpn_net_assoc_list(self, mock_get_db):
        with self.bgpvpn() as bgpvpn:
            bgpvpn_id = bgpvpn['bgpvpn']['id']
            with self.network() as net:
                net_id = net['network']['id']
                with self.assoc_net(bgpvpn_id, net_id=net_id):
                    res = 'bgpvpn/bgpvpns/' + bgpvpn_id + \
                          '/network_associations'
                    self._list(res)
                    mock_get_db.assert_called_once_with(mock.ANY,
                                                        bgpvpn_id,
                                                        mock.ANY, mock.ANY)

    @mock.patch.object(driver_api.BGPVPNDriver,
                       'delete_net_assoc_postcommit')
    @mock.patch.object(bgpvpn_db.BGPVPNPluginDb, 'delete_net_assoc')
    def test_delete_bgpvpn_net_assoc(self, mock_db_del, mock_postcommit):
        with self.bgpvpn() as bgpvpn:
            bgpvpn_id = bgpvpn['bgpvpn']['id']
            with self.network() as net:
                net_id = net['network']['id']
                with self.assoc_net(bgpvpn_id, net_id=net_id) as assoc:
                    assoc_id = assoc['network_association']['id']
                    net_assoc = {'id': assoc_id,
                                 'network_id': net_id,
                                 'bgpvpn_id': bgpvpn_id}
                    mock_db_del.return_value = net_assoc
            mock_db_del.assert_called_once_with(mock.ANY,
                                                assoc_id,
                                                bgpvpn_id)
            mock_postcommit.assert_called_once_with(mock.ANY,
                                                    net_assoc)