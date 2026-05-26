# NucPot AutoVC Phase 2 (L2: 参数化管线) 实施计划

> **前置条件**：Phase 1 已完成（31 tests passed, GitHub 推送成功）
> **目标**：用户可选择验证属性、配置参数，系统生成定制化的验证任务

## L1 → L2 的核心变化

| 维度 | L1 (当前) | L2 (目标) |
|------|----------|----------|
| 属性选择 | 固定 3 种 | 用户自选，支持 5+ 种 |
| 参数配置 | 硬编码默认值 | 用户可覆盖（timestep、cutoff、structure 等） |
| 参考值 | 硬编码 5 种材料 | 从 Supabase 数据库加载 |
| 势函数来源 | 手动注册 API | 支持 KIM Model ID 直接查询 |
| 结果展示 | JSON API | 含可视化评分报告 |

## 新增模块

### 1. 验证模板系统

```python
# src/autovc/core/templates.py

VERIFICATION_TEMPLATES = {
    "basic": {
        "name": "基础验证",
        "properties": ["lattice_constant", "cohesive_energy"],
        "description": "晶格常数 + 结合能，适合初步筛选",
        "estimated_time": "30s",
    },
    "mechanical": {
        "name": "力学性能验证",
        "properties": ["lattice_constant", "elastic_constants", "bulk_modulus"],
        "description": "弹性常数 + 体模量",
        "estimated_time": "2min",
    },
    "defect": {
        "name": "缺陷性质验证",
        "properties": ["vacancy_formation_energy"],
        "description": "空位形成能",
        "estimated_time": "1min",
    },
    "comprehensive": {
        "name": "全面验证",
        "properties": ["lattice_constant", "cohesive_energy", "elastic_constants",
                       "bulk_modulus", "vacancy_formation_energy"],
        "description": "所有 Phase 1/2 属性",
        "estimated_time": "5min",
    },
}
```

### 2. 参数化验证请求

```python
# schemas.py 新增

class ParameterizedVerificationRequest(BaseModel):
    potential_name: str
    template: str = "basic"  # or list of properties
    properties: list[str] | None = None  # override template
    parameters: dict = {}    # user overrides
    # parameters example: {"timestep": 0.001, "cutoff": 8.0, "structure": "BCC", "temperature": 0}
```

### 3. 从 Supabase 加载参考值

替代硬编码 reference/data.py，从 NucPot 主数据库的 parameters 表中读取实验/DFT 参考值。

### 4. 新增属性计算

- `bulk_modulus`：从弹性常数推导或直接 EV 曲线拟合
- `vacancy_formation_energy`：移除一个原子后计算能量差

## API 变更

```
GET  /api/templates          # 列出可用验证模板
POST /api/verification/v2    # 参数化验证请求
GET  /api/verification/{id}/report  # 结构化评分报告
```

## 实施步骤

| Step | 内容 | 依赖 |
|------|------|------|
| 1 | 新增 templates.py + API 端点 | Phase 1 |
| 2 | 扩展 schemas.py 支持参数化请求 | Step 1 |
| 3 | 新增 bulk_modulus 计算 | kimpy |
| 4 | 新增 vacancy_formation_energy 计算 | kimpy |
| 5 | 参考值从 Supabase 加载 | Supabase 迁移 |
| 6 | 验证报告生成端点 | Steps 1-5 |
| 7 | 全量测试更新 | Steps 1-6 |
