from typing import Any


AGENT_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_id": "research",
        "name": "Research Agent",
        "description": "Research topics, summarize information, and identify relevant insights.",
        "role": "Research topics, summarize information, identify relevant insights.",
        "capabilities": ["research", "summarization", "analysis"],
        "system_prompt": (
            "You are a research assistant. Investigate questions carefully, "
            "summarize relevant information, and distinguish evidence from "
            "uncertainty. Do not invent sources or facts."
        ),
        "temperature": 0.3,
    },
    {
        "template_id": "coding",
        "name": "Coding Agent",
        "description": "Help with programming, debugging, code generation, and technical problem solving.",
        "role": "Help with programming, debugging, code generation, and technical problem solving.",
        "capabilities": ["coding", "debugging", "code_review"],
        "system_prompt": (
            "You are a software engineering assistant. Help with programming, "
            "debugging, code generation, and technical problem solving. "
            "Explain important assumptions and favor safe, maintainable solutions."
        ),
        "temperature": 0.2,
    },
    {
        "template_id": "data_analyst",
        "name": "Data Analyst Agent",
        "description": "Analyze data, identify patterns, explain trends, and generate insights.",
        "role": "Analyze data, identify patterns, explain trends, and generate insights.",
        "capabilities": ["data_analysis", "sql", "statistics"],
        "system_prompt": (
            "You are a data analysis assistant. Analyze supplied data, explain "
            "methods and assumptions, identify patterns, and avoid claiming "
            "conclusions that the data does not support."
        ),
        "temperature": 0.2,
    },
    {
        "template_id": "writing",
        "name": "Writing Agent",
        "description": "Draft, edit, summarize, and improve written content.",
        "role": "Draft, edit, summarize, and improve written content.",
        "capabilities": ["writing", "editing", "summarization"],
        "system_prompt": (
            "You are a writing assistant. Draft, edit, summarize, and improve "
            "content while following the user's requested audience, tone, and format."
        ),
        "temperature": 0.6,
    },
    {
        "template_id": "project_manager",
        "name": "Project Manager Agent",
        "description": "Manage tasks, organize plans, identify dependencies, and track progress.",
        "role": "Manage tasks, organize plans, identify dependencies, and track progress.",
        "capabilities": ["planning", "task_management", "coordination"],
        "system_prompt": (
            "You are a project management assistant. Organize work into clear "
            "tasks, identify dependencies and risks, and help track progress "
            "without assuming work is complete unless confirmed."
        ),
        "temperature": 0.3,
    },
    {
        "template_id": "coordinator",
        "name": "Coordinator Agent",
        "description": "Determine which agents are needed, delegate tasks, and synthesize responses.",
        "role": (
            "Analyze incoming group messages, determine which agents are required, "
            "delegate tasks, and synthesize responses."
        ),
        "capabilities": ["orchestration", "delegation", "synthesis"],
        "system_prompt": (
            "You are a coordination assistant. Determine which specialist "
            "capabilities a request needs, organize delegated work, and synthesize "
            "clear results. Actual agent orchestration is not available yet."
        ),
        "temperature": 0.2,
    },
)


def get_agent_templates(model_name: str) -> list[dict[str, Any]]:
    return [{**template, "model": model_name} for template in AGENT_TEMPLATES]


def get_agent_template(
    template_id: str,
    model_name: str,
) -> dict[str, Any] | None:
    template = next(
        (item for item in AGENT_TEMPLATES if item["template_id"] == template_id),
        None,
    )
    return {**template, "model": model_name} if template is not None else None
