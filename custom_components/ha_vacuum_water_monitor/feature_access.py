"""Pure HA Tools feature policy, independent of HA and all IO.

These decisions grant only tool access. Callers must also enforce fresh native
HA resource permissions before IO, after awaits and immediately before actions.
Policy editing remains admin-only. Visibility never implies read or execute
access, and the configured scope can only narrow Home Assistant permissions.
"""
import json
import math
import unicodedata

_MAX_BYTES = 64 * 1024
_MAX_DEPTH = 64
_CATALOG = {
    'water': {'visible': 'household', 'read': 'household', 'execute': 'household'},
    'settings': {'visible': 'household', 'read': 'household', 'execute': 'household'},
    'measurements': {'visible': 'household', 'read': 'household', 'execute': 'household'},
}
_MODES = frozenset(('inherit', 'household', 'admin', 'selected_users'))
_ERROR = 'invalid_feature_access'


def default_feature_access():
    """Return a fresh policy preserving the catalog's legacy role defaults."""
    return {'schema': 1, 'features': {}}


def _bounded_json(value):
    """Bound traversal before serialization; reject cycles and non-JSON values.

    The byte budget here is a lower bound; final JSON encoding also accounts
    for escaping. Pending children, nodes, strings and nesting are bounded so
    even hostile oversized input cannot cause an unbounded deepcopy/JSON walk.
    """
    stack = [(value, 0, False)]
    ancestors = set()
    budget = nodes = 0
    while stack:
        item, depth, leaving = stack.pop()
        kind = type(item)
        if leaving:
            ancestors.remove(id(item))
            continue
        nodes += 1
        if nodes > _MAX_BYTES or depth > _MAX_DEPTH:
            raise ValueError(_ERROR)
        if kind in (dict, list):
            length = len(item)
            if id(item) in ancestors or length > _MAX_BYTES:
                raise ValueError(_ERROR)
            if len(stack) + length > _MAX_BYTES:
                raise ValueError(_ERROR)
            budget += 2 + max(0, length - 1)
            ancestors.add(id(item))
            stack.append((item, depth, True))
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str or len(key) > _MAX_BYTES:
                        raise ValueError(_ERROR)
                    budget += len(key.encode('utf-8')) + 3
                    if budget > _MAX_BYTES:
                        raise ValueError(_ERROR)
                    stack.append((child, depth + 1, False))
            else:
                stack.extend((child, depth + 1, False) for child in item)
        elif kind is str:
            if len(item) > _MAX_BYTES:
                raise ValueError(_ERROR)
            budget += len(item.encode('utf-8')) + 2
        elif item is None or kind is bool:
            budget += 4 if item is None or item is True else 5
        elif kind is int:
            if item.bit_length() > _MAX_BYTES:
                raise ValueError(_ERROR)
            budget += max(1, item.bit_length() // 4)
        elif kind is float and math.isfinite(item):
            budget += 1
        else:
            raise ValueError(_ERROR)
        if budget > _MAX_BYTES:
            raise ValueError(_ERROR)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > _MAX_BYTES:
        raise ValueError(_ERROR)


def _valid_user_id(value):
    return (type(value) is str and 0 < len(value) <= 128
            and value == value.strip()
            and not any(unicodedata.category(char) == 'Cc' for char in value))


def validate_feature_access(policy):
    """Return detached normalized strict schema 1 JSON, or a safe ValueError."""
    try:
        _bounded_json(policy)
        if (type(policy) is not dict or set(policy) != {'schema', 'features'}
                or type(policy['schema']) is not int or policy['schema'] != 1
                or type(policy['features']) is not dict):
            raise ValueError(_ERROR)
        features = {}
        for feature, operations in policy['features'].items():
            if feature not in _CATALOG or type(operations) is not dict:
                raise ValueError(_ERROR)
            clean = {}
            for operation, rule in operations.items():
                if operation not in _CATALOG[feature] or type(rule) is not dict:
                    raise ValueError(_ERROR)
                mode = rule.get('mode')
                if type(mode) is not str or mode not in _MODES:
                    raise ValueError(_ERROR)
                if set(rule) - {'mode', 'user_ids', 'entity_ids'}:
                    raise ValueError(_ERROR)
                if mode != 'selected_users' and 'user_ids' in rule:
                    raise ValueError(_ERROR)
                ids = rule.get('user_ids', [])
                entities = rule.get('entity_ids')
                if type(ids) is not list or len(ids) > 128 or not all(_valid_user_id(uid) for uid in ids):
                    raise ValueError(_ERROR)
                if entities is not None and (type(entities) is not list or len(entities) > 128 or
                    not all(type(entity) is str and entity.startswith('vacuum.') and 7 < len(entity) <= 255 for entity in entities)):
                    raise ValueError(_ERROR)
                clean[operation] = {'mode': mode}
                if mode == 'selected_users':
                    clean[operation]['user_ids'] = sorted(set(ids))
                if entities is not None:
                    clean[operation]['entity_ids'] = sorted(set(entities))
            features[feature] = clean
        return {'schema': 1, 'features': features}
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError(_ERROR) from None


def _allowed(policy, feature, operation, user_id, is_active, is_admin, entity_id=None):
    if (type(feature) is not str or feature not in _CATALOG
            or type(operation) is not str or operation not in _CATALOG[feature]):
        return False
    if is_active is not True or not _valid_user_id(user_id):
        return False
    if is_admin is True:
        return True
    rule = policy['features'].get(feature, {}).get(operation, {'mode': 'inherit'})
    if entity_id is not None and 'entity_ids' in rule and entity_id not in rule['entity_ids']:
        return False
    mode = rule['mode']
    if mode == 'inherit':
        mode = _CATALOG[feature][operation]
    return mode == 'household' or (mode == 'selected_users' and user_id in rule['user_ids'])


def feature_access_allowed(policy, feature, operation, *, user_id, is_active, is_admin, entity_id=None):
    """Validate every call; evaluate only this tool's independent operation gate.

    user_id and flags must come from the fresh actual authenticated HA user,
    never a client-supplied target. A malformed policy always raises ValueError.
    Even an active admin cannot bypass malformed input or unsupported operations.
    """
    normalized = validate_feature_access(policy)
    return _allowed(normalized, feature, operation, user_id, is_active, is_admin, entity_id)


def effective_feature_capabilities(policy, *, user_id, is_active, is_admin):
    """Project catalog operation booleans without exposing IDs or allowlists."""
    normalized = validate_feature_access(policy)
    return {feature: {operation: _allowed(normalized, feature, operation, user_id, is_active, is_admin)
                      for operation in operations}
            for feature, operations in _CATALOG.items()}


async def check_access(hass, user_id, feature, operation, entities=(), *, policy=None):
    """Check fresh HA identity, tool policy and native entity permissions.

    An internal call with no user keeps legacy automation behavior only while
    no explicit tool policy exists; once configured it has no user grant.
    """
    from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
    from .const import DATA_STORAGE, DOMAIN
    if policy is None:
        storage = hass.data.get(DOMAIN, {}).get(DATA_STORAGE)
        if storage is None:
            return False
        policy = await storage.async_get_access_policy()
    try:
        policy = validate_feature_access(policy)
    except ValueError:
        return False
    if user_id is None:
        return not policy['features']
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_active:
        return False
    try:
        if not feature_access_allowed(policy, feature, operation, user_id=user.id,
                                      is_active=user.is_active, is_admin=user.is_admin):
            return False
        rule = policy['features'].get(feature, {}).get(operation, {})
        if not user.is_admin and operation == 'execute' and 'entity_ids' in rule and not entities:
            return False
        for entity in entities:
            if not feature_access_allowed(policy, feature, operation, user_id=user.id,
                                          is_active=user.is_active, is_admin=user.is_admin, entity_id=entity):
                return False
            required = POLICY_CONTROL if operation == 'execute' else POLICY_READ
            if not user.permissions.check_entity(entity, required):
                return False
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# The guard propagates the *actual* authenticated caller to the Store. It is
# checked while the integration's Store lock is held, immediately before IO.
from contextvars import ContextVar
from asyncio import current_task

_write_guard = ContextVar('vwm_feature_write_guard', default=None)


def set_write_guard(user_id, feature, entities, *, admin=False, read_entities=()):
    return _write_guard.set((current_task(), user_id, feature, tuple(entities), admin, tuple(read_entities)))


def reset_write_guard(token):
    _write_guard.reset(token)


async def enforce_write_guard(hass, settings):
    from homeassistant.exceptions import Unauthorized
    guard = _write_guard.get()
    if guard is None:
        return
    owner, user_id, feature, entities, admin, read_entities = guard
    # Child tasks (periodic accounting, issue sync) inherit context variables
    # but are not the caller's action and must not inherit its authority.
    if owner is not current_task():
        return
    if admin:
        user = await hass.auth.async_get_user(user_id) if user_id else None
        if user is None or not user.is_active or not user.is_admin:
            raise Unauthorized()
    features = (feature,) if isinstance(feature, str) else feature
    for item in features:
        if not await check_access(hass, user_id, item, 'execute', entities,
                                  policy=settings['feature_access'] if 'feature_access' in settings else default_feature_access()):
            raise Unauthorized()
    if not await check_native_read(hass, user_id, read_entities):
        raise Unauthorized()


async def check_native_read(hass, user_id, entities):
    """A binding cannot expose an HA source that its caller cannot read."""
    from homeassistant.auth.permissions.const import POLICY_READ
    if not entities or user_id is None:
        return True
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_active:
        return False
    return all(user.permissions.check_entity(entity, POLICY_READ) for entity in entities)
