# GPU 机器开发指引

> 生成日期：2026-06-15
> 目标：在有 GPU 的机器上克隆 Veritas 并继续 YOLOv5 adapter 开发

> 当前状态：本指南服务于后续 ELIS YOLOv5 adapter 开发。当前 `audit-paper` 主链路不依赖 YOLOv5 权重；`visual.panel_extraction` 仍是 OpenCV 过渡实现，`visual.copy_move` 仍是 ORB/SIFT 过渡实现。

---

## 1. 克隆仓库

```bash
# 在有 GPU 的机器上执行
git clone git@github.com:MedgeAI/veritas.git
cd veritas

# 按维护者指定分支工作；当前仓库默认分支可能是 master
git status --short

# 初始化 ELIS submodule（包含 YOLOv5 panel-extractor 等）
git submodule update --init --recursive
```

---

## 2. 安装依赖

```bash
# Python 依赖（uv 管理）
make sync

# 或手动安装
uv sync
```

**关键依赖**：
- PyTorch >= 1.9（GPU 版本）
- torchvision
- opencv-python
- numpy
- Pillow
- tqdm

**GPU 版本 PyTorch 安装**（如果需要 CUDA 12.1）：
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

---

## 3. 下载模型权重

```bash
# 下载 YOLOv5 panel extraction 模型（~50MB，需要科学上网）
make download-models

# 或手动下载
pip install gdown
gdown --id 1CuSUYUF0uTbcANFRffzoMUllCP8Du-HT
unzip panel_extraction_models.zip -d models/panel_extraction/
```

**预期结果**：
- 模型文件：`models/panel_extraction/model_4_class.pt`（或 `model_5_class.pt`）
- 大小：~50MB

---

## 4. 验证 YOLOv5 panel-extractor

```bash
# 测试 YOLOv5 panel-extractor 是否能正常运行
cd third_party/elis/system_modules/panel-extractor

# 创建测试图像
python -c "
from PIL import Image
import numpy as np
img = np.random.randint(100, 200, (640, 640, 3), dtype=np.uint8)
img[50:150, 50:150] = [255, 0, 0]  # Red panel
img[200:350, 100:350] = [0, 255, 0]  # Green panel
Image.fromarray(img).save('test_input.png')
"

# 运行 panel extraction
python extract.py \
  --input-path test_input.png \
  --output-path ./test_output \
  --weights ../../../models/panel_extraction/model_4_class.pt \
  --device cpu \
  --save_img True

# 检查结果
ls -la test_output/
cat test_output/PANELS.csv
```

**预期输出**：
- `test_output/PANELS.csv`：包含检测到的 panel bbox 和类别
- `test_output/*.png`：裁剪的 panel 图像

---

## 5. 编写 YOLOv5 Adapter

**目标文件**：`engine/static_audit/tools/panel_extraction.py`

**任务清单**：
1. 阅读 `third_party/elis/system_modules/panel-extractor/extract.py`，理解 API
2. 重写 `panel_extraction.py`，内部调用 YOLOv5 `extract.run()`
3. 更新 `PanelEvidence` schema，增加 `panel_type` 字段
4. 删除 OpenCV Canny/contour/filter_contours 代码
5. 重写测试：`tests/unit/test_panel_extraction.py`

**Adapter 结构**：
```python
# engine/static_audit/tools/panel_extraction.py
import sys
from pathlib import Path

# Add ELIS panel-extractor to path
ELIS_PANEL_EXTRACTOR = Path(__file__).parent.parent.parent / "third_party" / "elis" / "system_modules" / "panel-extractor"
sys.path.insert(0, str(ELIS_PANEL_EXTRACTOR))

from extract import run as yolov5_run

def extract_panels(
    figure_path: Path,
    *,
    figure_id: str,
    output_dir: Path,
    weights_path: Path = Path("models/panel_extraction/model_4_class.pt"),
    device: str = "cpu",
    conf_thres: float = 0.4,
    iou_thres: float = 0.4,
) -> dict:
    """
    Extract panels from figure image using YOLOv5.
    
    Returns:
    {
        "schema_version": "1.0",
        "status": "ran",
        "figure_id": "FE-0001",
        "panel_count": 4,
        "panels": [
            {
                "panel_id": "PE-0001-01",
                "label": "a",
                "panel_type": "Blot",  # NEW FIELD
                "bbox": [x0, y0, x1, y1],
                "crop_path": "panels/FE-0001/a.png",
                ...
            }
        ],
        ...
    }
    """
    # Create temporary output directory for YOLOv5
    yolov5_output = output_dir / "yolov5_temp"
    yolov5_output.mkdir(parents=True, exist_ok=True)
    
    # Call YOLOv5
    yolov5_run(
        input_path=[str(figure_path)],
        output_path=str(yolov5_output),
        weights=str(weights_path),
        device=device,
        conf_thres=conf_thres,
        iou_thres=iou_thres,
        save_img=True,
    )
    
    # Parse YOLOv5 output (PANELS.csv)
    panels = _parse_yolov5_output(yolov5_output, figure_id, output_dir)
    
    # Build result
    return {
        "schema_version": "1.0",
        "status": "ran",
        "figure_id": figure_id,
        "panel_count": len(panels),
        "panels": panels,
        ...
    }

def _parse_yolov5_output(yolov5_output: Path, figure_id: str, output_dir: Path) -> list:
    """Parse PANELS.csv and convert to PanelEvidence format."""
    csv_path = yolov5_output / "PANELS.csv"
    panels = []
    
    with open(csv_path) as f:
        lines = f.readlines()[1:]  # Skip header
        for idx, line in enumerate(lines):
            parts = line.strip().split(", ")
            fig_name, panel_id, label, x0, y0, x1, y1 = parts
            
            # Move crop to final location
            crop_src = yolov5_output / f"{fig_name}_{panel_id}_{label}.png"
            crop_dst = output_dir / "panels" / figure_id / f"{chr(ord('a') + idx)}.png"
            crop_dst.parent.mkdir(parents=True, exist_ok=True)
            crop_src.rename(crop_dst)
            
            panels.append({
                "panel_id": f"PE-{figure_id}-{idx + 1:02d}",
                "label": chr(ord("a") + idx),
                "panel_type": label,  # NEW FIELD: Blot/Graph/Microscopy/etc.
                "bbox": [int(float(x0)), int(float(y0)), int(float(x1)), int(float(y1))],
                "crop_path": str(crop_dst.relative_to(output_dir)),
                ...
            })
    
    return panels
```

---

## 6. 更新 Schema

**目标文件**：`engine/static_audit/visual_schemas.py`

**修改**：
```python
@dataclass
class PanelEvidence:
    panel_id: str
    parent_figure_id: str
    label: str
    bbox: list[int]
    crop_path: str
    width: int
    height: int
    extraction_confidence: float
    extraction_method: str
    panel_type: str | None = None  # NEW: "Blot" / "Graph" / "Microscopy" / "Body Imagery" / "Flow Cytometry" / "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

## 7. 删除 OpenCV 代码

**目标文件**：`engine/static_audit/tools/panel_extraction.py`

**删除**：
- `detect_edges()`
- `connect_edges()`
- `find_contours()`
- `filter_contours()`
- `sort_contours_by_position()`
- `assign_panel_labels()`
- 所有 OpenCV import

**保留**：
- `extract_panels()`（重写为调用 YOLOv5）
- `build_figure_evidence_from_ledger()`

---

## 8. 重写测试

**目标文件**：`tests/unit/test_panel_extraction.py`

**任务**：
1. 删除所有绑定 OpenCV 行为的测试
2. 创建 YOLOv5 golden fixture（用真实论文图像）
3. 验证 `panel_type` 字段正确
4. 验证 bbox 和 crop 正确

**测试结构**：
```python
def test_yolov5_panel_extraction():
    """Test YOLOv5 panel extraction on real figure."""
    figure_path = Path("tests/fixtures/real_paper_figure.png")
    result = extract_panels(
        figure_path,
        figure_id="FE-0001",
        output_dir=tmp_path,
        device="cpu",  # or "cuda" if GPU available
    )
    
    assert result["status"] == "ran"
    assert result["panel_count"] > 0
    for panel in result["panels"]:
        assert "panel_type" in panel
        assert panel["panel_type"] in ["Blot", "Graph", "Microscopy", "Body Imagery", "Flow Cytometry", "unknown"]
        assert "bbox" in panel
        assert "crop_path" in panel
```

---

## 9. 验证

```bash
# 运行测试
make test

# 或单独运行 visual tests
uv run pytest tests/unit/test_visual_*.py -v

# 运行完整 audit（如果有真实论文）
make audit PAPER_DIR=<paper_dir> CASE_ID=<case_id>
```

---

## 10. 提交 + 推送

提交前必须先确认 `make test` 和 `make lint-python`。不要提交模型权重、真实论文、真实运行产物、`outputs/`、`web_data/` 或本地密钥。分支和提交信息按维护者要求执行；不要从本指南机械复制固定分支名。

---

## 11. 下一步

**Phase 2: Keypoint Copy-Move 增强**
- 阅读 `third_party/elis/system_modules/copy-move-detection-keypoint/`
- 重写 `copy_move_detection.py`，调用 RootSIFT+MAGSAC++
- 删除 ORB 代码路径

**Phase 3: SILA Dense Copy-Move**
- 阅读 `third_party/elis/system_modules/copy-move-detection/`
- 新增 `copy_move_dense.py`

**Phase 4: TruFor Adapter**
- 阅读 `third_party/elis/system_modules/TruFor/`
- 新增 `tru_for.py`（GPU 检测 + skip 语义）

---

## 常见问题

### Q: 模型下载失败（网络问题）

**A**: 手动从 Google Drive 下载，然后上传到 GPU 机器：
1. 在有网络的机器上：`gdown --id 1CuSUYUF0uTbcANFRffzoMUllCP8Du-HT`
2. 用 scp/rsync 传输到 GPU 机器
3. 解压到 `models/panel_extraction/`

### Q: YOLOv5 推理很慢（CPU）

**A**: 使用 GPU：
```python
yolov5_run(
    ...,
    device="0",  # GPU 0
)
```

### Q: 模型权重路径不对

**A**: 检查 `models/panel_extraction/` 目录下是否有 `.pt` 文件：
```bash
ls models/panel_extraction/*.pt
```

### Q: PyTorch CUDA 不可用

**A**: 重新安装 GPU 版本 PyTorch：
```bash
pip uninstall torch torchvision -y
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

---

## 参考文档

- [`ELIS_REUSE_DECISIONS.md`](ELIS_REUSE_DECISIONS.md) - ELIS 复用决策
- [`docs/product/Veritas-视觉取证增强调研PRD-ELIS超集方案.md`](docs/product/Veritas-视觉取证增强调研PRD-ELIS超集方案.md) - 调研 PRD
- [`AGENTS.md`](AGENTS.md) - 项目操作指南
- [`TODO.md`](TODO.md) - 当前 TODO
