import unittest

from unittest.mock import patch

from flask_pysaml2_example import create_app


class FakeSubject:
    def __init__(self, text):
        self.text = text


class FakeAuthnResponse:
    def __init__(self, user_id='person@example.com', in_response_to='request-id'):
        self._subject = FakeSubject(user_id)
        self.in_response_to = in_response_to
        self.ava = {'FirstName': ['Pat'], 'LastName': ['Lee']}

    def get_identity(self):
        return self.ava

    def get_subject(self):
        return self._subject


class AuthRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                'TESTING': True,
                'SECRET_KEY': 'test-secret',
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                'SAML_IDP_SETTINGS': {
                    'example-idp': {
                        'entityid': 'http://flask-pysaml2-example',
                        'metadata_url': 'https://idp.example.test/metadata.xml',
                    }
                },
            }
        )
        self.client = self.app.test_client()

    def test_metadata_endpoint_exposes_acs_for_idp(self):
        response = self.client.get('/auth/saml/metadata/example-idp')

        self.assertEqual(response.status_code, 200)
        self.assertIn('AssertionConsumerService', response.get_data(as_text=True))
        self.assertIn('/auth/saml/sso/example-idp', response.get_data(as_text=True))

    @patch('flask_pysaml2_example.auth.saml_client_for')
    def test_saml_login_tracks_outstanding_request_and_rejects_unsafe_next(self, mock_saml_client_for):
        fake_client = mock_saml_client_for.return_value
        fake_client.prepare_for_authenticate.return_value = (
            'request-id',
            {'headers': [('Location', 'https://idp.example.test/sso')]},
        )

        response = self.client.get('/auth/saml/login/example-idp?next=https://evil.example')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, 'https://idp.example.test/sso')
        fake_client.prepare_for_authenticate.assert_called_once_with(relay_state='/user')

        with self.client.session_transaction() as session_state:
            self.assertIn('request-id', session_state['saml_outstanding_requests'])

    @patch('flask_pysaml2_example.auth.saml_client_for')
    def test_saml_sso_falls_back_to_user_page_for_unsafe_relay_state(self, mock_saml_client_for):
        fake_client = mock_saml_client_for.return_value
        fake_client.parse_authn_request_response.return_value = FakeAuthnResponse()

        with self.client.session_transaction() as session_state:
            session_state['saml_outstanding_requests'] = {'request-id': '/user'}

        response = self.client.post(
            '/auth/saml/sso/example-idp',
            data={
                'SAMLResponse': 'signed-response',
                'RelayState': 'https://evil.example',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/user'))

        with self.client.session_transaction() as session_state:
            self.assertNotIn('request-id', session_state.get('saml_outstanding_requests', {}))


if __name__ == '__main__':
    unittest.main()
