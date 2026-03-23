import time

from typing import TYPE_CHECKING, Any, TypedDict, cast

from urllib.parse import urlparse
from xml.sax.saxutils import escape

import requests

from flask import Blueprint, Response, abort, current_app, redirect, request, session, url_for
from flask_login import login_required, login_user, logout_user
from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT

from . import db
from .orm import User


if TYPE_CHECKING:
    from saml2.client import Saml2Client


class MetadataCacheEntry(TypedDict):
    """Cached IdP metadata payload and insertion timestamp."""

    metadata: str
    cached_at: float


auth_blueprint = Blueprint('auth', __name__)
# Demo-only in-process cache; use a proper shared cache backend in production.
_METADATA_CACHE: dict[str, MetadataCacheEntry] = {}


def _get_idp_settings(idp_name: str) -> dict[str, Any]:
    """Return configuration for the requested IdP name."""

    idp_settings = cast(dict[str, Any], current_app.config['SAML_IDP_SETTINGS'])
    if idp_name not in idp_settings:
        raise KeyError(f'Settings for IDP "{idp_name}" not found on SAML_IDP_SETTINGS.')
    return cast(dict[str, Any], idp_settings[idp_name])


def _get_idp_metadata(metadata_url: str) -> str:
    """Fetch IdP metadata XML with simple in-memory TTL caching."""

    ttl = int(current_app.config.get('SAML_METADATA_CACHE_TTL_SECONDS', 3600))
    timeout = float(current_app.config.get('SAML_METADATA_TIMEOUT_SECONDS', 5))
    now = time.time()
    cached_entry = _METADATA_CACHE.get(metadata_url)
    if cached_entry and now - cached_entry['cached_at'] < ttl:
        return cached_entry['metadata']

    response = requests.get(metadata_url, timeout=timeout)
    response.raise_for_status()
    _METADATA_CACHE[metadata_url] = {
        'metadata': response.text,
        'cached_at': now,
    }
    return response.text


def _is_safe_redirect_url(url: str) -> bool:
    """Allow only relative paths or hosts explicitly trusted by config."""

    parsed_url = urlparse(url)

    if parsed_url.scheme in ('',) and not parsed_url.netloc:
        return url.startswith('/')

    if parsed_url.scheme not in ('http', 'https'):
        return False

    allowed_hosts = set(cast(list[str] | tuple[str, ...], current_app.config.get('ALLOWED_REDIRECT_HOSTS', ())))
    allowed_hosts.add(request.host)
    return parsed_url.netloc in allowed_hosts


def _resolve_relay_state(default_redirect: str) -> str:
    """Resolve RelayState from the SAML POST while enforcing safe redirects."""

    relay_state = request.form.get('RelayState')
    if not relay_state:
        return default_redirect

    if _is_safe_redirect_url(relay_state):
        return relay_state

    current_app.logger.warning('Unsafe RelayState was ignored')
    return default_redirect


def _get_attribute(
    available_attributes: dict[str, list[str]],
    attribute_names: tuple[str, ...],
    default: str = '',
) -> str:
    """Return the first non-empty attribute value from known aliases."""

    for attribute_name in attribute_names:
        if attribute_name in available_attributes and available_attributes[attribute_name]:
            return available_attributes[attribute_name][0]
    return default


def _build_sp_metadata_xml(idp_name: str) -> str:
    """Build minimal SP metadata XML for a given IdP configuration."""

    idp_settings = _get_idp_settings(idp_name)
    acs_url = url_for('auth.saml_sso', idp_name=idp_name, _external=True)
    entity_id = str(idp_settings.get('entityid', acs_url))

    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<md:EntityDescriptor xmlns:md=\"urn:oasis:names:tc:SAML:2.0:metadata\" entityID=\"{escape(entity_id)}\">
  <md:SPSSODescriptor protocolSupportEnumeration=\"urn:oasis:names:tc:SAML:2.0:protocol\" WantAssertionsSigned=\"true\">
    <md:AssertionConsumerService Binding=\"urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST\" Location=\"{escape(acs_url)}\" index=\"1\" isDefault=\"true\" />
  </md:SPSSODescriptor>
</md:EntityDescriptor>
""".strip()


def load_user(user_id: str) -> User | None:
    """Resolve a logged-in principal from its SAML subject identifier."""

    return User.query.filter_by(email=user_id).first()


def _saml_client_for_request(idp_name: str) -> 'Saml2Client':
    """Create a SAML client and map initialization failures to HTTP errors."""

    try:
        return saml_client_for(idp_name)
    except KeyError:
        current_app.logger.info('Unknown SAML IdP requested: %s', idp_name)
        abort(404)
    except requests.RequestException:
        current_app.logger.warning('Failed to fetch SAML metadata for IdP %s', idp_name, exc_info=True)
        abort(502)
    except Exception:
        current_app.logger.exception('Failed to initialize SAML client for IdP %s', idp_name)
        abort(500)


def saml_client_for(idp_name: str) -> 'Saml2Client':
    """Build and return a configured pysaml2 client for one IdP."""

    idp_settings = _get_idp_settings(idp_name)

    acs_url = url_for('auth.saml_sso', idp_name=idp_name, _external=True)
    https_acs_url = url_for('auth.saml_sso', idp_name=idp_name, _external=True, _scheme='https')

    metadata = _get_idp_metadata(str(idp_settings['metadata_url']))
    entityid = str(idp_settings.get('entityid', acs_url))

    from saml2.client import Saml2Client
    from saml2.config import Config as Saml2Config

    settings: dict[str, Any] = {
        'entityid': entityid,
        'metadata': {'inline': [metadata]},
        'service': {
            'sp': {
                'endpoints': {
                    'assertion_consumer_service': [
                        (acs_url, BINDING_HTTP_REDIRECT),
                        (acs_url, BINDING_HTTP_POST),
                        (https_acs_url, BINDING_HTTP_REDIRECT),
                        (https_acs_url, BINDING_HTTP_POST),
                    ],
                },
                # Validate responses against known authn request IDs.
                'allow_unsolicited': False,
                # Most IdPs support unsigned requests; keep this configurable.
                'authn_requests_signed': bool(idp_settings.get('authn_requests_signed', False)),
                'logout_requests_signed': True,
                'want_assertions_signed': True,
                'want_response_signed': bool(idp_settings.get('want_response_signed', True)),
            }
        },
    }

    saml2_config = Saml2Config()
    saml2_config.load(settings)
    saml2_config.allow_unknown_attributes = True
    return Saml2Client(config=saml2_config)


@auth_blueprint.route('/saml/sso/<idp_name>', methods=['POST'])
def saml_sso(idp_name: str) -> Response:
    """Handle ACS POSTs, validate assertions, and establish a local session."""

    saml_response = request.form.get('SAMLResponse')
    if not saml_response:
        current_app.logger.info('Missing SAMLResponse for IdP %s', idp_name)
        abort(400)

    saml_client = _saml_client_for_request(idp_name)

    outstanding_requests = cast(dict[str, str], session.get('saml_outstanding_requests', {}))
    try:
        authn_response = saml_client.parse_authn_request_response(
            saml_response,
            BINDING_HTTP_POST,
            outstanding=outstanding_requests,
        )
    except Exception:
        current_app.logger.warning('Invalid SAML response for IdP %s', idp_name, exc_info=True)
        abort(401)

    authn_response.get_identity()
    subject = authn_response.get_subject()
    user_id = subject.text if subject else None
    if not user_id:
        current_app.logger.warning('SAML response missing subject for IdP %s', idp_name)
        abort(401)

    in_response_to = getattr(authn_response, 'in_response_to', None)
    if in_response_to:
        outstanding_requests.pop(in_response_to, None)
        session['saml_outstanding_requests'] = outstanding_requests

    try:
        # This is known as "Just In Time (JIT) provisioning".
        user = load_user(user_id)
        if user is None:
            db_session = db.session()
            attribute_mapping = cast(
                dict[str, tuple[str, ...]],
                current_app.config.get('SAML_ATTRIBUTE_MAPPING', {}),
            )
            user = User(
                email=user_id,
                first_name=_get_attribute(
                    authn_response.ava,
                    attribute_mapping.get('first_name', ('FirstName',)),
                    default='',
                ),
                last_name=_get_attribute(
                    authn_response.ava,
                    attribute_mapping.get('last_name', ('LastName',)),
                    default='',
                ),
            )
            db_session.add(user)
            db_session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to provision user during SAML login for %s', user_id)
        abort(500)

    session['saml_attributes'] = authn_response.ava
    login_user(user)

    redirect_url = _resolve_relay_state(url_for('user'))
    current_app.logger.info('User %s successfully authenticated via SAML', user_id)
    return redirect(redirect_url)


@auth_blueprint.route('/saml/login/<idp_name>')
def saml_login(idp_name: str) -> Response:
    """Start SP-initiated login by redirecting to the IdP SSO endpoint."""

    saml_client = _saml_client_for_request(idp_name)
    relay_state = request.args.get('next', url_for('user'))
    if not _is_safe_redirect_url(relay_state):
        relay_state = url_for('user')

    try:
        reqid, info = saml_client.prepare_for_authenticate(relay_state=relay_state)
    except Exception:
        current_app.logger.exception('Failed to prepare SAML AuthnRequest for IdP %s', idp_name)
        abort(500)

    outstanding_requests = cast(dict[str, str], session.get('saml_outstanding_requests', {}))
    outstanding_requests[reqid] = relay_state
    session['saml_outstanding_requests'] = outstanding_requests

    # Select the IdP URL to send the AuthN request to.
    try:
        _, redirect_url = next(filter(lambda k_v: k_v[0] == 'Location', info['headers']))
    except (KeyError, StopIteration):
        current_app.logger.error('SAML client did not return redirect location for IdP %s', idp_name)
        abort(502)

    response = redirect(redirect_url, code=302)

    # Section 3.2.3.2 of the SAML HTTP Redirect binding recommends disabling cache.
    response.headers['Cache-Control'] = 'no-cache, no-store'
    response.headers['Pragma'] = 'no-cache'
    return response


@auth_blueprint.route('/saml/metadata/<idp_name>', methods=['GET'])
def saml_metadata(idp_name: str) -> Response:
    """Return SP metadata XML for the selected IdP setup."""

    try:
        metadata_xml = _build_sp_metadata_xml(idp_name)
        return Response(metadata_xml, mimetype='application/samlmetadata+xml')
    except KeyError:
        abort(404)


@auth_blueprint.route('/logout')
@login_required
def logout() -> Response:
    """Clear the local authenticated session and return to the index page."""

    logout_user()
    return redirect(url_for('index'))
