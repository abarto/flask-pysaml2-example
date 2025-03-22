import requests

from flask import abort, Blueprint, current_app, redirect, request, session, url_for
from flask_login import login_required, login_user, logout_user
from saml2 import (
    BINDING_HTTP_POST,
    BINDING_HTTP_REDIRECT
)
from saml2.client import Saml2Client
from saml2.config import Config as Saml2Config

from . import db
from .orm import User


auth_blueprint = Blueprint('auth', __name__)


def load_user(user_id):
    return User.query.filter_by(email=user_id).first()


def saml_client_for(idp_name):
    """
    Given the name of an IdP, return a configuation.
    The configuration is a hash for use by saml2.config.Config
    """

    if idp_name not in current_app.config['SAML_IDP_SETTINGS']:
        raise Exception(f'Settings for IDP "{idp_name}" not found on SAML_IDP_SETTINGS.')
    
    acs_url = url_for(
        'auth.saml_sso',
        idp_name=idp_name,
        _external=True)
    
    https_acs_url = url_for(
        'auth.saml_sso',
        idp_name=idp_name,
        _external=True,
        _scheme='https')

    # SAML metadata changes very rarely. On a production system,
    # this data should be cached as approprate for your production system.
    rv = requests.get(current_app.config['SAML_IDP_SETTINGS'][idp_name]['metadata_url'])

    current_app.logger.debug('rv.rext: %s', rv.text)

    entityid = current_app.config['SAML_IDP_SETTINGS'][idp_name].get('entityid', acs_url)

    settings = {
        'entityid': entityid,
        'metadata': {
            'inline': [rv.text],
        },
        'service': {
            'sp': {
                'endpoints': {
                    'assertion_consumer_service': [
                        (acs_url, BINDING_HTTP_REDIRECT),
                        (acs_url, BINDING_HTTP_POST),
                        (https_acs_url, BINDING_HTTP_REDIRECT),
                        (https_acs_url, BINDING_HTTP_POST)
                    ],
                },
                # Don't verify that the incoming requests originate from us via
                # the built-in cache for authn request ids in pysaml2
                'allow_unsolicited': True,
                # Don't sign authn requests, since signed requests only make
                # sense in a situation where you control both the SP and IdP
                'authn_requests_signed': False,
                'logout_requests_signed': True,
                'want_assertions_signed': True,
                'want_response_signed': False
            }
        }
    }

    current_app.logger.info('settings: %s', settings)

    saml2_config = Saml2Config()
    saml2_config.load(settings)
    saml2_config.allow_unknown_attributes = True
    
    saml2_client = Saml2Client(config=saml2_config)
    
    return saml2_client


def _is_safe_redirect_url(url: str) -> bool:
    """Checks if the redirect URL is safe."""
    return (
        not url.startswith('http://') and 
        not url.startswith('https://') or
        url.startswith(current_app.config.get('ALLOWED_REDIRECT_DOMAINS', []))
    )


@auth_blueprint.route("/saml/sso/<idp_name>", methods=['POST'])
def saml_sso(idp_name):
    try:
        saml_client = saml_client_for(idp_name)

        current_app.logger.debug('request.form: %s', request.form)

        authn_response = saml_client.parse_authn_request_response(
            request.form['SAMLResponse'],
            BINDING_HTTP_POST
        )

        current_app.logger.info('authn_response: %s', authn_response)

        authn_response.get_identity()
        
        subject = authn_response.get_subject()

        current_app.logger.info('subject: %s', subject)

        user_id = subject.text

        # This is what as known as "Just In Time (JIT) provisioning".
        # What that means is that, if a user in a SAML assertion
        # isn't in the user store, we create that user first, then log them in

        user = load_user(user_id)
        if user is None:
            db_session = db.session()
            user = User(
                email=user_id,

                # These user attributes are supplied by the IdP.
                first_name=authn_response.ava['FirstName'][0],
                last_name=authn_response.ava['LastName'][0]
            )
            db_session.add(user)
            db_session.commit()
        
        session['saml_attributes'] = authn_response.ava

        login_user(user)

        redirect_url = url_for('user')

        # Replace the existing RelayState handling
        if request.form.get('RelayState'):
            redirect_url = request.form['RelayState']
            if not _is_safe_redirect_url(redirect_url):
                current_app.logger.warning('Potentially malicious RelayState URL blocked')
                redirect_url = url_for('user')

        current_app.logger.debug('Processing SAML response')
        current_app.logger.info('User %s successfully authenticated via SAML', user_id)

        return redirect(redirect_url)
    except Exception as e:
        current_app.logger.exception('Exception raised during SAML SSO login')
        abort(401)


@auth_blueprint.route("/saml/login/<idp_name>")
def saml_login(idp_name):
    saml_client = saml_client_for(idp_name)
    reqid, info = saml_client.prepare_for_authenticate()

    current_app.logger.info('reqid: %s', reqid)
    current_app.logger.info('info: %s', info)

    redirect_url = None

    # Select the IdP URL to send the AuthN request to
    _, redirect_url = next(filter(lambda k_v: k_v[0] == 'Location', info['headers']))

    current_app.logger.info('redirect_url: %s', redirect_url)
    
    response = redirect(redirect_url, code=302)
    
    # NOTE:
    #   I realize I _technically_ don't need to set Cache-Control or Pragma:
    #     http://stackoverflow.com/a/5494469
    #   However, Section 3.2.3.2 of the SAML spec suggests they are set:
    #     http://docs.oasis-open.org/security/saml/v2.0/saml-bindings-2.0-os.pdf
    #   We set those headers here as a "belt and suspenders" approach,
    #   since enterprise environments don't always conform to RFCs
    response.headers['Cache-Control'] = 'no-cache, no-store'
    response.headers['Pragma'] = 'no-cache'
    
    return response


@auth_blueprint.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))
