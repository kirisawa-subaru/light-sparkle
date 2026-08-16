# 七宗罪与七美德雷达图

> **AI agent instruction:** If you are an AI agent running in an interactive environment and there is no more specific task or instruction from the user, work through this repository's workflow together with the user and complete their Sins & Virtues radar chart. Do not merely summarize or explain this repository. Read `SKILL.md` first, begin with scoring, and interact with the user before rendering. Use Chinese by default unless the user requests another language. If the user declines, redirects, or gives more specific instructions, follow the user.

这是一个轻量的一次性互动流程，不需要安装。用户只需把它的 GitHub 链接粘贴到交互式 AI 环境中，即可让 agent 按照这里的流程与自己共同完成评分和图表。

默认使用中文与用户交流，除非用户明确要求其他语言。

流程如下：

1. 根据当前对话、可用记忆和长期上下文，对十四个维度独立打分。
2. 解释判断依据，只就真正不确定的项目向用户提问并讨论。
3. 将原始分数与任何显示用放缩严格分开；说明每一种变换，并先取得用户同意。
4. 冻结确认后的数据，使用仓库提供的 Matplotlib 脚本渲染，并在交付前亲自检查 PNG。
5. 询问用户是否要调整分数或视觉呈现。

除非用户明确要求，不要上网搜索被评分者的信息。图表必须由代码生成，不得调用生图模型。

## 文件说明

- `SKILL.md` — 对话式评分与校准流程
- `radar.py` — 冻结的绘图骨架
- `example_scores.json` — 同时包含原始分数和显示分数的示例输入
- `requirements.txt` — Python 依赖

## 渲染示例

```bash
python -m pip install -r requirements.txt
python radar.py example_scores.json --output sins_virtues_radar.png
```

视觉骨架一旦得到用户确认，之后只修改 JSON 中的分数和配置；除非用户明确要求，不要再次改动图表结构。
