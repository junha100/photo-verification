"""Read original-file provenance without treating missing metadata as authenticity."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

IPTC_NS = 'http://iptc.org/std/Iptc4xmpExt/2008-02-29/'
SOURCE_TYPES = {
    'trainedAlgorithmicMedia': 'ai_generated',
    'compositeWithTrainedAlgorithmicMedia': 'ai_edited',
    'digitalCapture': 'camera_capture_claim',
}

def source_kind(value):
    for prefix in ('http://cv.iptc.org/newscodes/digitalsourcetype/', 'https://cv.iptc.org/newscodes/digitalsourcetype/'):
        if isinstance(value, str) and value.startswith(prefix):
            return SOURCE_TYPES.get(value[len(prefix):], 'other')
    return 'other'

def xmp_claims(packet):
    if not packet:
        return [], 'not_present'
    raw = packet.encode('utf-8') if isinstance(packet, str) else packet
    if len(raw) > 2_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        return [], 'unsupported_or_unsafe_xml'
    try:
        tree = ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        return [], 'parse_error'
    values = []
    tag = '{' + IPTC_NS + '}DigitalSourceType'
    for node in tree.iter():
        if tag in node.attrib: values.append(node.attrib[tag])
        if node.tag == tag:
            value = node.attrib.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource') or node.text
            if value: values.append(value.strip())
    return [{'source': 'xmp_iptc', 'kind': source_kind(v), 'value': v, 'authenticated': False} for v in sorted(set(values))], 'read'

def c2pa_claims(report):
    active = report.get('active_manifest')
    manifest = report.get('manifests', {}).get(active, {})
    claims = []
    # Only active-manifest actions: do not mistake ingredient history for whole-file generation.
    for assertion in manifest.get('assertions', []):
        if assertion.get('label', '').split('.v')[0] != 'c2pa.actions': continue
        for action in assertion.get('data', {}).get('actions', []):
            value = action.get('digitalSourceType')
            if value:
                claims.append({'source': 'c2pa_active_action', 'kind': source_kind(value), 'value': value, 'action': action.get('action'), 'authenticated': False})
    return claims

def inspect_provenance(path):
    path = Path(path)
    result = {'file': path.name, 'status': 'no_ai_record_found', 'claims': [], 'xmp_status': 'not_present',
              'c2pa': {'status': 'not_checked', 'signer_trust': 'not_established'},
              'watermark': 'not_checked',
              'notice': '기록 없음은 실제 사진이라는 뜻이 아닙니다. 일반 메타데이터는 수정될 수 있으며, 서명자 신뢰 확인 전에는 AI 생성 사실로 확정하지 않습니다.'}
    try:
        with Image.open(path) as im:
            if im.format not in ('JPEG', 'PNG', 'WEBP'):
                result['status'] = 'unsupported_format'
                return result
            packet = im.info.get('xmp') or im.info.get('XML:com.adobe.xmp')
            result['claims'], result['xmp_status'] = xmp_claims(packet)
    except (OSError, ValueError):
        result['status'] = 'file_read_error'
        return result
    try:
        from c2pa import Reader, Context, C2paError
        # Local inspection only; do not follow URLs embedded in untrusted files.
        context = Context.from_dict({'verify': {'remote_manifest_fetch': False, 'fetch_ocsp': False}, 'core': {'allowed_network_hosts': []}})
        try:
            with Reader(str(path), context=context) as reader:
                report = json.loads(reader.json())
            result['c2pa'].update(status='read', validation_state=report.get('validation_state', 'Unknown'),
                                  validation_status=report.get('validation_status', []), active_manifest=report.get('active_manifest'))
            result['claims'].extend(c2pa_claims(report))
        except C2paError.ManifestNotFound:
            result['c2pa']['status'] = 'not_present'
        except C2paError:
            result['c2pa']['status'] = 'read_or_validation_error'
        finally:
            context.close()
    except ImportError:
        result['c2pa']['status'] = 'library_unavailable'
    if any(c['kind'] in ('ai_generated', 'ai_edited') for c in result['claims']):
        result['status'] = 'ai_record_found_unverified'
    if result['c2pa'].get('validation_state') == 'Invalid':
        result['status'] = 'invalid_provenance'
    elif result['status'] == 'no_ai_record_found' and (result['xmp_status'] in ('parse_error', 'unsupported_or_unsafe_xml') or result['c2pa']['status'] in ('read_or_validation_error', 'library_unavailable')):
        result['status'] = 'inspection_incomplete'
    return result
