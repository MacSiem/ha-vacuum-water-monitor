"""Privacy-safe measurement intake; eligibility never approves a runtime rate.

The vocabulary below constrains exported technical text. It is NOT a declaration
that every model supports these settings or that different contexts are equivalent.
Model/setting applicability still requires independent maintainer qualification.
"""
from copy import deepcopy
import math
import re
from uuid import UUID, uuid4

MEASUREMENT_INTAKE_URL = 'https://github.com/MacSiem/vacuum-consumption-data/issues/new?template=measurement.yml'
SETTINGS = ('mop_mode','water_level','route','passes','wash_mode','wash_frequency',
            'wash_temperature','adaptive_mode','detergent_mode','cleaning_mode',
            'task_scope','suction_level','carpet_policy')
AXES = ('model_id','sku','dock_variant','firmware','integration_id','integration_version','reservoir','action')
QUALITY = {'boundaries_confirmed':True,'uninterrupted':True,'exposure_complete':True,
           'settings_constant':True,'context_recorded_at_collection':True,
           'intervening_refill':False,'unmeasured_transfer':False}
VOCABULARY = {
    'mop_mode':{'fast','standard','deep','deep_plus','custom','normal','quick'},
    'water_level':{'off','low','mild','medium','moderate','high','intense','extreme','custom'},
    'route':{'fast','standard','deep','deep_plus','normal','quick','custom'},
    'passes':{'1','2','3'},
    'wash_mode':{'light','standard','balanced','deep','smart','eco','normal','intensive'},
    'adaptive_mode':{'on','off','auto'},'detergent_mode':{'on','off','auto'},
    'cleaning_mode':{'vac_and_mop','vacuum_and_mop','vacuum_only','vac_only','mop_only','vacuum','mopping','sweeping'},
    'task_scope':{'full','whole_home','zone','room','segment','spot','manual'},
    'suction_level':{'off','quiet','low','balanced','medium','high','turbo','max','max_plus','standard','gentle'},
    'carpet_policy':{'avoid','avoidance','lift','mop_lift','mop_raise','vacuum_only','do_not_mop','ignore','adaptive'},
}
LIMITATIONS = [
    'Experimental measured contribution; independent maintainer review required.',
    'One device does not establish applicability to other devices or settings.',
    'Whole-cycle measurements cannot separate floor, wash and transfer rates.',
    'Unknown or unsupported technical text is omitted and must be qualified before runtime use.',
    'Technical metadata can allow re-identification; GitHub submissions expose the submitting account.',
    'Request withdrawal through the repository; public copies may remain.',
]
SAMPLE_KEYS = {'context','area_m2','measured_ml','resolution_ml','instrument','purpose','scope','quality'}
PACKET_KEYS = {'schema_version','kind','contribution_id','licence','publication_consent',
               'runtime_eligible','review','samples','unknowns','limitations','intake_url'}


def _positive(value):
    if type(value) not in (int,float) or value <= 0 or value > 1e100 or not math.isfinite(value):
        raise ValueError('A finite positive physical quantity is required')
    return value


def _setting(key, value):
    if type(value) is not str:
        return None
    if value == 'not_applicable':
        return value
    if value in VOCABULARY.get(key,set()):
        return value
    if key == 'water_level' and re.fullmatch(r'[0-9]{1,3}',value) and int(value) <= 100:
        return value
    if key == 'wash_frequency' and re.fullmatch(r'[0-9]{1,3}(min|m2)',value):
        return value if 0 < int(re.match(r'[0-9]+',value)[0]) <= 120 else None
    if key == 'wash_temperature' and re.fullmatch(r'[0-9]{1,2}_c',value):
        return value
    return None


def _version(value):
    # Deliberately exclude four-part dotted addresses and arbitrary labels.
    return value if type(value) is str and re.fullmatch(r'[0-9]{1,4}(\.[0-9]{1,3}){1,2}',value) else None


def _public_context(context, public_catalog):
    if not isinstance(context,dict) or not isinstance(public_catalog,dict):
        raise ValueError('Recorded context and public model catalog are required')
    if type(context.get('model_id')) is not str:
        raise ValueError('A catalog model identifier is required')
    model = public_catalog.get(context['model_id'])
    if not isinstance(model,dict):
        raise ValueError('Model is not in the reviewed public catalog')
    integration, reservoir = context.get('integration_id'), context.get('reservoir')
    if (type(integration) is not str or integration not in model.get('integration_adapters',model.get('integration_candidates',[]))
            or type(reservoir) is not str or reservoir not in {'dock_clean','dock_dirty','robot_clean','robot_dirty','detergent'}
            or reservoir not in model.get('reservoirs_ml',{})):
        raise ValueError('Select a catalog integration and reservoir')
    settings = context.get('settings')
    if not isinstance(settings,dict):
        raise ValueError('Historical settings are required')
    return {'model_id':context['model_id'],
        'sku':context.get('sku') if type(context.get('sku')) is str and context.get('sku') in {'EU','US','UK','CN','AU','global','not_applicable'} else None,
        'dock_variant':context.get('dock_variant') if type(context.get('dock_variant')) is str and context.get('dock_variant') in {'tank','plumbed','no_dock','not_applicable'} else None,
        'firmware':_version(context.get('firmware')), 'integration_id':integration,
        'integration_version':_version(context.get('integration_version')),
        'reservoir':reservoir, 'action':'whole_cycle',
        'settings':{key:_setting(key,settings.get(key)) for key in SETTINGS}}


def _sample(sample, public_catalog, *, local):
    if not isinstance(sample,dict) or (local and sample.get('confirmed') is not True):
        raise ValueError('Select a previously confirmed physical measurement')
    if not local and set(sample) != SAMPLE_KEYS:
        raise ValueError('Missing or unapproved sample fields')
    quality = sample.get('quality')
    if (not isinstance(quality,dict) or set(quality) != set(QUALITY)
            or any(quality[key] is not expected for key,expected in QUALITY.items())):
        raise ValueError('Complete measurement quality confirmations are required')
    context = _public_context(sample.get('context'),public_catalog)
    if not local and (set(sample['context']) != set(AXES)|{'settings'} or sample['context'] != context):
        raise ValueError('Unsafe or unsupported context fields')
    volume = _positive(sample.get('observed_ml') if local else sample.get('measured_ml'))
    resolution = _positive(sample.get('resolution_ml'))
    area = _positive(sample.get('area_m2'))
    capacity = public_catalog[context['model_id']].get('reservoirs_ml',{}).get(context['reservoir'])
    if resolution >= volume or (type(capacity) in (int,float) and volume > capacity + resolution):
        raise ValueError('Measured refill/resolution contradict the reservoir capacity')
    if (sample.get('instrument') not in {'graduated_jug','scale_water','flow_meter'}
            or sample.get('purpose') not in {'training','validation'} or sample.get('scope') != 'whole_cycle'
            or sample.get('context',{}).get('action') != 'whole_cycle'):
        raise ValueError('A measured whole-cycle sample and instrument are required')
    return {'context':context,'area_m2':area,'measured_ml':volume,'resolution_ml':resolution,
            'instrument':sample['instrument'],'purpose':sample['purpose'],'scope':'whole_cycle','quality':dict(QUALITY)}


def _unknowns(samples):
    result=set()
    for sample in samples:
        ctx=sample['context']
        result.update('context.'+k for k in AXES if ctx[k] is None)
        result.update('context.settings.'+k for k,v in ctx['settings'].items() if v is None)
    return sorted(result)


def build_confirmed_contribution(samples, *, public_catalog, consent_cc_by_4_0=False):
    """Return a local preview by default. Nothing here performs network I/O."""
    if type(consent_cc_by_4_0) is not bool or not isinstance(samples,list) or not 1 <= len(samples) <= 50:
        raise ValueError('Select one to fifty confirmed measured cycles')
    seen=set(); device=None; projected=[]
    for sample in samples:
        clean=_sample(sample,public_catalog,local=True)
        identity, current_device=sample.get('id'),sample.get('device_id')
        if (type(identity) is not str or not identity or identity in seen
                or type(current_device) is not str or not current_device):
            raise ValueError('Distinct local cycles and a local device are required')
        if device is not None and device != current_device:
            raise ValueError('One device per contribution')
        seen.add(identity);device=current_device;projected.append(clean)
    return {'schema_version':1,'kind':'confirmed_measurement_contribution','contribution_id':str(uuid4()),
        'licence':'CC-BY-4.0','publication_consent':consent_cc_by_4_0,'runtime_eligible':False,
        'review':{'status':'experimental','review_needed':True},'samples':projected,
        'unknowns':_unknowns(projected),'limitations':list(LIMITATIONS),'intake_url':MEASUREMENT_INTAKE_URL}


def validate_contribution(payload, *, public_catalog):
    """Reject unsafe intake. Even valid consented measurements require review."""
    rejected={'submission_eligible':False,'review_needed':True,'runtime_eligible':False,'reason':'invalid_contribution'}
    try:
        if not isinstance(payload,dict) or set(payload) != PACKET_KEYS:
            return rejected
        if (type(payload['schema_version']) is not int or payload['schema_version'] != 1
                or payload['kind'] != 'confirmed_measurement_contribution'
                or payload['licence'] != 'CC-BY-4.0' or payload['publication_consent'] is not True
                or payload['runtime_eligible'] is not False
                or payload['review'] != {'status':'experimental','review_needed':True}
                or type(payload['review'].get('review_needed')) is not bool
                or payload['limitations'] != LIMITATIONS or payload['intake_url'] != MEASUREMENT_INTAKE_URL):
            return rejected
        identifier=UUID(payload['contribution_id'])
        if identifier.version != 4 or str(identifier) != payload['contribution_id']:
            return rejected
        if not isinstance(payload['samples'],list) or not 1 <= len(payload['samples']) <= 50:
            return rejected
        samples=[_sample(s,public_catalog,local=False) for s in payload['samples']]
        if payload['unknowns'] != _unknowns(samples):
            return rejected
        return {'submission_eligible':True,'review_needed':True,'runtime_eligible':False,'reason':'experimental_manual_review'}
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return rejected
