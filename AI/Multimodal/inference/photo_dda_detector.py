"""Local DDA inference using pinned official code and the full official checkpoint."""
from __future__ import annotations
import ast
import importlib.util
import hashlib
import json
import math
import sys
import threading
import types
from pathlib import Path
import torch
from PIL import Image
from torchvision import transforms

_ROOT = Path(__file__).resolve().parents[3]
_BUNDLE = _ROOT / '.local' / 'dda-detector'
_LOCK = threading.Lock()
_MODEL = None
_MODEL_MODE = None
_ACTIVE_HEAD_CONFIG = _BUNDLE / "active-head.json"
_TRANSFORM = transforms.Compose([
    transforms.CenterCrop(336), transforms.ToTensor(),
    transforms.Normalize([0.48145466, 0.4578275, 0.40821073], [0.26862954, 0.26130258, 0.27577711]),
])

def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _apply_adapted_head(model, config_path: Path | None = None):
    config_path = _ACTIVE_HEAD_CONFIG if config_path is None else config_path
    model._photo_dda_info = {"variant": "pretrained"}
    if not config_path.exists():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("version") != 1:
        raise RuntimeError("지원하지 않는 DDA 판정부 설정입니다.")
    relative = Path(config["head_path"])
    path = (_ROOT / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(_ROOT.resolve()):
        raise RuntimeError("DDA 판정부 경로가 프로젝트 범위를 벗어납니다.")
    if _sha256_file(path) != config["head_sha256"]:
        raise RuntimeError("추가 학습한 DDA 판정부 파일이 변경되었습니다.")
    if _sha256_file(_BUNDLE / "DDA_ckpt.pth") != config["base_checkpoint_sha256"]:
        raise RuntimeError("DDA 기반 가중치가 추가 학습 때 사용한 가중치와 다릅니다.")
    head = torch.load(path, map_location="cpu", weights_only=True)
    for key in ("base_checkpoint_sha256", "manifest_sha256", "preprocessing"):
        if head.get(key) != config[key]:
            raise RuntimeError("DDA 판정부의 학습 정보가 설정과 일치하지 않습니다.")
    state = {key: head[key] for key in ("weight", "bias")}
    for key, expected in model.base_model.fc.state_dict().items():
        actual = state[key]
        if not isinstance(actual, torch.Tensor) or actual.dtype != expected.dtype or actual.shape != expected.shape or not torch.isfinite(actual).all():
            raise RuntimeError("추가 학습한 DDA 판정부 값이 올바르지 않습니다.")
    model.base_model.fc.load_state_dict(state, strict=True)
    model._photo_dda_info = {"variant": "adapted-head", "headSha256": config["head_sha256"], "manifestSha256": config["manifest_sha256"]}


def _load_model(*, use_adapted_head: bool = True):
    global _MODEL, _MODEL_MODE
    if _MODEL is not None:
        if _MODEL_MODE != use_adapted_head:
            raise RuntimeError("원본 DDA와 추가 학습 DDA는 별도 프로세스에서 실행해주세요.")
        return _MODEL
    sys.path.insert(0, str(_BUNDLE / 'dinov2'))
    from dinov2.hub.backbones import dinov2_vitl14
    package_name = '_photo_dda_official_models'
    directory = _BUNDLE / 'upstream' / 'Inference' / 'models'
    package = types.ModuleType(package_name)
    package.__path__ = [str(directory)]
    sys.modules[package_name] = package
    # Replace only the backbone provider call: full DDA weights are loaded below,
    # so downloading the original DINO pretraining weights is redundant.
    source_path = directory / 'dinov2_models.py'
    tree = ast.parse(source_path.read_text(encoding='utf-8'))
    replaced = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == 'torch' and node.func.value.attr == 'hub' and node.func.attr == 'load':
            node.func = ast.Name(id='_local_backbone', ctx=ast.Load())
            replaced += 1
    if replaced != 1:
        raise RuntimeError('DDA 모델 코드의 구조가 예상과 다릅니다.')
    def local_backbone(repository, name, pretrained=True):
        if repository != 'facebookresearch/dinov2' or name != 'dinov2_vitl14':
            raise ValueError('지원하지 않는 DDA 기반 모델입니다.')
        return dinov2_vitl14(pretrained=False)
    base_name = package_name + '.dinov2_models'
    base = types.ModuleType(base_name)
    base.__package__ = package_name
    base.__dict__['_local_backbone'] = local_backbone
    sys.modules[base_name] = base
    exec(compile(ast.fix_missing_locations(tree), str(source_path), 'exec'), base.__dict__)
    wrapper_name = package_name + '.dinov2_models_lora'
    spec = importlib.util.spec_from_file_location(wrapper_name, directory / 'dinov2_models_lora.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[wrapper_name] = module
    spec.loader.exec_module(module)
    with torch.device('meta'):
        model = module.DINOv2ModelWithLoRA(name='dinov2_vitl14', lora_rank=8, lora_alpha=1, lora_targets=None)
    checkpoint = torch.load(_BUNDLE / 'DDA_ckpt.pth', map_location='cpu', weights_only=True, mmap=True)
    model.load_state_dict(checkpoint['model'], strict=True, assign=True)
    if any(p.is_meta for p in model.parameters()):
        raise RuntimeError('DDA 가중치를 완전히 불러오지 못했습니다.')
    if use_adapted_head:
        _apply_adapted_head(model)
    else:
        model._photo_dda_info = {"variant": "pretrained"}
    _MODEL_MODE = use_adapted_head
    _MODEL = model.eval()
    return _MODEL

def predict_dda(image_path: Path) -> float:
    # Serialize loading/inference; the HTTP server can receive concurrent requests.
    with _LOCK, torch.inference_mode():
        model = _load_model()
        with Image.open(image_path) as image:
            tensor = _TRANSFORM(image.convert('RGB')).unsqueeze(0)
        output = model(tensor).sigmoid().flatten()
        if output.numel() != 1 or not torch.isfinite(output).all():
            raise RuntimeError('DDA 모델이 올바른 점수를 반환하지 않았습니다.')
        return float(output.item())

def combine_photo_scores(existing_fake: float, dda_fake: float) -> dict:
    values = [float(existing_fake), float(dda_fake)]
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError('사진 판별 점수는 0~1 사이여야 합니다.')
    # Fixed OR rule at 0.5. This score is not a calibrated probability.
    fake = max(values)
    return {'fake': fake, 'real': 1 - fake,
            'existingFake': values[0], 'ddaFake': values[1],
            'disagreement': (values[0] > 0.5) != (values[1] > 0.5),
            'rule': 'max-score; either detector > 0.5 flags AI signal'}


def select_photo_score(existing_fake: float, dda_fake: float) -> dict:
    """Use the better benchmarked DDA as primary; retain old output for comparison."""
    comparison = combine_photo_scores(existing_fake, dda_fake)
    comparison.update(fake=float(dda_fake), real=1.0-float(dda_fake),
                      rule='DDA primary; existing model is comparison only')
    comparison["ddaModel"] = dict(getattr(_MODEL, "_photo_dda_info", {"variant": "not-loaded"}))
    return comparison


_REGION_NAMES = ('center', 'top_left', 'top_right', 'bottom_left', 'bottom_right')

def _dda_region_tensors(image: Image.Image):
    """Keep native resolution; pad undersized images exactly like CenterCrop."""
    from torchvision.transforms import functional as functional
    width, height = image.size
    if width < 336 or height < 336:
        image = functional.pad(image, [max((336-width)//2, 0), max((336-height)//2, 0),
                                       max((337-width)//2, 0), max((337-height)//2, 0)])
    tl, tr, bl, br, center = functional.five_crop(image, [336, 336])
    return [_TRANSFORM(crop) for crop in (center, tl, tr, bl, br)]

def aggregate_dda_regions(scores, method: str) -> float:
    import statistics
    values = [float(score) for score in scores]
    if len(values) != 5 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError('5개 영역의 점수가 올바르지 않습니다.')
    if method == 'mean':
        return float(statistics.mean(values))
    if method == 'median':
        return float(statistics.median(values))
    if method in ('center50', 'center75'):
        center_weight = .5 if method == 'center50' else .75
        return float(center_weight * values[0] + (1-center_weight) * statistics.mean(values[1:]))
    raise ValueError('지원하지 않는 영역 결합 방식입니다.')

def predict_dda_regions(image_path: Path, batch_size: int = 1, center_score: float | None = None) -> dict:
    """Experimental five-crop inference. Production remains center-only."""
    import hashlib
    if center_score is not None and (not math.isfinite(center_score) or not 0 <= center_score <= 1):
        raise ValueError('저장된 중앙 영역 점수가 올바르지 않습니다.')
    if batch_size not in (1, 2, 5):
        raise ValueError('지원하지 않는 영역 배치 크기입니다.')
    with _LOCK, torch.inference_mode():
        model = _load_model()
        with Image.open(image_path) as image:
            tensors = _dda_region_tensors(image.convert('RGB'))
        # Narrow/small images can produce identical crops. Evaluate each unique
        # tensor once and map it back, preserving the fixed five-area rule.
        unique, indices, hashes = [], [], {}
        if center_score is not None:
            hashes[hashlib.sha256(tensors[0].numpy().tobytes()).hexdigest()] = -1
        for tensor in tensors:
            digest = hashlib.sha256(tensor.numpy().tobytes()).hexdigest()
            if digest not in hashes:
                hashes[digest] = len(unique)
                unique.append(tensor)
            indices.append(hashes[digest])
        probabilities = torch.cat([model(torch.stack(unique[start:start+batch_size])).sigmoid().flatten()
                                   for start in range(0, len(unique), batch_size)]) if unique else torch.empty(0)
        if probabilities.numel() != len(unique) or not torch.isfinite(probabilities).all():
            raise RuntimeError('영역별 DDA 점수를 계산하지 못했습니다.')
        scores = [float(center_score) if index == -1 else float(probabilities[index].item()) for index in indices]
        return {'regions': dict(zip(_REGION_NAMES, scores)), 'scores': scores,
                'center': scores[0], 'mean': aggregate_dda_regions(scores, 'mean'),
                'median': aggregate_dda_regions(scores, 'median'),
                'center50': aggregate_dda_regions(scores, 'center50'),
                'center75': aggregate_dda_regions(scores, 'center75'), 'uniqueRegions': len(set(indices)), 'evaluatedRegions': len(unique)}
