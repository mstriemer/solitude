from urlparse import urlparse, parse_qs

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import reverse

import mock
import requests
import test_utils
from nose.tools import eq_

from lib.bango.constants import HEADERS_SERVICE_GET
from lib.bango.tests import samples

from lib.paypal.constants import HEADERS_URL_GET, HEADERS_TOKEN_GET
from lib.paypal.map import urls


class Proxy(test_utils.TestCase):

    def setUp(self):
        request = mock.patch('lib.proxy.views.requests', name='test.proxy')
        self.req = request.start()
        self.req.exceptions = requests.exceptions
        self.req.patcher = request
        self.addCleanup(request.stop)


@mock.patch.object(settings, 'SOLITUDE_PROXY', True)
class TestPaypal(Proxy):

    def setUp(self):
        super(TestPaypal, self).setUp()
        self.url = reverse('paypal.proxy')

    def test_proxy(self):
        self.req.post.return_value.status_code = 200
        self.req.post.return_value.text = 'some-text'
        res = self.client.post(self.url, **{HEADERS_URL_GET: 'get-pay-key'})
        eq_(self.req.post.call_args[0][0], urls['get-pay-key'])
        eq_(res.status_code, 200)
        eq_(res.content, 'some-text')

    def test_not_present(self):
        with self.assertRaises(KeyError):
            self.client.post(self.url)

    def test_proxy_auth(self):
        self.req.get.return_value.status_code = 200
        self.client.get(self.url, **{HEADERS_URL_GET: 'get-pay-key',
                                     HEADERS_TOKEN_GET: 'token=b&secret=f'})
        assert ('X-PAYPAL-AUTHORIZATION' in
                self.req.post.call_args[1]['headers'])

    def test_status_code(self):
        self.req.post.return_value.status_code = 123
        res = self.client.post(self.url, **{HEADERS_URL_GET: 'get-pay-key'})
        eq_(res.status_code, 123)

    def test_result(self):
        self.req.post.side_effect = self.req.exceptions.RequestException()
        with self.settings(DEBUG=False):
            res = self.client.post(self.url,
                                   **{HEADERS_URL_GET: 'get-pay-key'})
            eq_(res.status_code, 500)

    def test_not_enabled(self):
        with self.settings(SOLITUDE_PROXY=False):
            eq_(self.client.post(self.url).status_code, 404)


@mock.patch.object(settings, 'SOLITUDE_PROXY', True)
@mock.patch.object(settings, 'BANGO_AUTH', {'USER': 'me', 'PASSWORD': 'shh'})
class TestBango(Proxy):

    def setUp(self):
        super(TestBango, self).setUp()
        self.url = reverse('bango.proxy')

    def test_not_present(self):
        with self.assertRaises(KeyError):
            self.client.post(self.url, samples.sample_request,
                             **{'content_type': 'text/xml'})

    def sample(self, data=samples.sample_request, **hdrs):
        headers = {'content_type': 'text/xml',
                   HEADERS_SERVICE_GET: 'http://url.com/b'}
        headers.update(**hdrs)
        self.client.post(self.url, data, **headers)

    def test_header(self):
        self.sample(HTTP_X_SOLITUDE_SOAPACTION='foo')
        eq_(self.req.post.call_args[1]['headers']['SOAPAction'], 'foo')

    def test_use_user_id(self):
        self.sample(HTTP_X_BANGO_USE_MERCHANT_IDENTIFIER='foo')
        eq_(self.req.post.call_args[1]['headers']
            ['X-Bango-Use-Merchant-Identifier'], 'foo')

    def test_good(self):
        self.sample()
        body = self.req.post.call_args[1]['data']
        assert '<ns0:username>me</ns0:username>' in body
        assert '<ns0:password>shh</ns0:password>' in body

    def test_billing(self):
        self.sample(data=samples.billing_request)
        body = self.req.post.call_args[1]['data']
        assert '<ns1:username>me</ns1:username>' in body
        assert '<ns1:password>shh</ns1:password>' in body

    def test_refund(self):
        self.sample(data=samples.refund_request)
        body = self.req.post.call_args[1]['data']
        assert '<ns0:username>me</ns0:username>' in body
        assert '<ns0:password>shh</ns0:password>' in body


@mock.patch.object(settings, 'SOLITUDE_PROXY', True)
@mock.patch.object(
    settings, 'ZIPPY_CONFIGURATION',
    {'f': {'url': 'http://f.c', 'auth': {'key': 'k', 'secret': 's'}}})
class TestProvider(Proxy):

    def setUp(self):
        super(TestProvider, self).setUp()
        self.url = (reverse('provider.proxy', kwargs={'reference_name': 'f'})
                    + '/f/b/')

    def test_not_setup(self):
        with self.settings(ZIPPY_CONFIGURATION={}):
            with self.assertRaises(ImproperlyConfigured):
                self.client.get(self.url)

    def test_call(self):
        self.client.get(self.url)
        args = self.req.get.call_args
        assert 'OAuth realm' in args[1]['headers']['Authorization']
        eq_(args[0][0], 'http://f.c/f/b/')

    def test_type(self):
        self.client.get(self.url, CONTENT_TYPE='t/c', HTTP_ACCEPT='t/c')
        eq_(self.req.get.call_args[1]['headers']['Content-Type'], 't/c')
        eq_(self.req.get.call_args[1]['headers']['Accept'], 't/c')

    def test_post(self):
        self.client.post(self.url, data={'foo': 'bar'})
        assert 'foo' in self.req.post.call_args[1]['data']

    def test_get(self):
        self.client.get(self.url, data={'baz': 'quux'})
        assert '?baz=quux' in self.req.get.call_args[0][0]


@mock.patch.object(settings, 'SOLITUDE_PROXY', True)
@mock.patch.object(
    settings, 'ZIPPY_CONFIGURATION',
    {'boku': {'url': 'http://f.c', 'auth': {'secret': 's', 'key': 'f'}}})
class TestBoku(Proxy):

    def setUp(self):
        super(TestBoku, self).setUp()
        self.url = reverse('provider.proxy', kwargs={'reference_name': 'boku'})
        self.url = self.url + '/billing/request?f=b'

    def test_call(self):
        self.client.get(self.url)

        sig = parse_qs(urlparse(self.req.get.call_args[0][0]).query)['sig']
        assert sig, 'A sig parameter should have been added'
