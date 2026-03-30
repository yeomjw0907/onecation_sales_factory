import importlib.util
import os
from copy import deepcopy
from typing import Any, List

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from sales_factory.tools import NotionLogTool

# Optional: web scrape tool for auditor & competitor analyst (crewai[tools] required)
try:
    from crewai_tools import ScrapeWebsiteTool
    _scrape_tool = ScrapeWebsiteTool()
except Exception:
    _scrape_tool = None


PROVIDER_FALLBACKS = {
    "anthropic": "gemini/gemini-2.5-pro",
}


def _has_provider(provider_name: str) -> bool:
    if provider_name == "anthropic":
        return importlib.util.find_spec("anthropic") is not None and bool(
            os.environ.get("ANTHROPIC_API_KEY", "").strip()
        )
    return True


def resolve_llm_model(llm_name: str | None) -> str | None:
    if not llm_name or "/" not in llm_name:
        return llm_name

    provider_name = llm_name.split("/", 1)[0].strip().lower()
    if _has_provider(provider_name):
        return llm_name

    return PROVIDER_FALLBACKS.get(provider_name, llm_name)


@CrewBase
class SalesFactory:
    """SalesFactory crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    def _agent_config(self, agent_name: str) -> dict[str, Any]:
        config = deepcopy(self.agents_config[agent_name])  # type: ignore[index]
        config["llm"] = resolve_llm_model(config.get("llm"))
        return config

    @agent
    def lead_finder(self) -> Agent:
        return Agent(
            config=self._agent_config("lead_finder"),
            verbose=True,
        )

    @agent
    def website_auditor(self) -> Agent:
        tools = [_scrape_tool] if _scrape_tool else []
        return Agent(
            config=self._agent_config("website_auditor"),
            tools=[t for t in tools if t is not None],
            verbose=True,
        )

    @agent
    def lead_verifier(self) -> Agent:
        tools = [_scrape_tool] if _scrape_tool else []
        return Agent(
            config=self._agent_config("lead_verifier"),
            tools=[t for t in tools if t is not None],
            verbose=True,
        )

    @agent
    def identity_disambiguator(self) -> Agent:
        return Agent(
            config=self._agent_config("identity_disambiguator"),
            verbose=True,
        )

    @agent
    def competitor_analyst(self) -> Agent:
        tools = [_scrape_tool] if _scrape_tool else []
        return Agent(
            config=self._agent_config("competitor_analyst"),
            tools=[t for t in tools if t is not None],
            verbose=True,
        )

    @agent
    def landing_page_builder(self) -> Agent:
        return Agent(
            config=self._agent_config("landing_page_builder"),
            verbose=True,
        )

    @agent
    def marketing_strategist(self) -> Agent:
        return Agent(
            config=self._agent_config("marketing_strategist"),
            verbose=True,
        )

    @agent
    def proposal_writer(self) -> Agent:
        return Agent(
            config=self._agent_config("proposal_writer"),
            verbose=True,
        )

    @agent
    def proposal_localizer(self) -> Agent:
        return Agent(
            config=self._agent_config("proposal_localizer"),
            verbose=True,
        )

    @agent
    def email_writer(self) -> Agent:
        return Agent(
            config=self._agent_config("email_writer"),
            verbose=True,
        )

    @agent
    def email_localizer(self) -> Agent:
        return Agent(
            config=self._agent_config("email_localizer"),
            verbose=True,
        )

    @agent
    def notion_logger(self) -> Agent:
        return Agent(
            config=self._agent_config("notion_logger"),
            tools=[NotionLogTool()],
            verbose=True,
        )

    @task
    def lead_research_task(self) -> Task:
        return Task(
            name="lead_research_task",
            config=self.tasks_config["lead_research_task"],  # type: ignore[index]
            output_file="lead_research.md",
        )

    @task
    def identity_disambiguation_task(self) -> Task:
        return Task(
            name="identity_disambiguation_task",
            config=self.tasks_config["identity_disambiguation_task"],  # type: ignore[index]
            output_file="identity_disambiguation.md",
        )

    @task
    def lead_verification_task(self) -> Task:
        return Task(
            name="lead_verification_task",
            config=self.tasks_config["lead_verification_task"],  # type: ignore[index]
            output_file="lead_verification.md",
        )

    @task
    def website_audit_task(self) -> Task:
        return Task(
            name="website_audit_task",
            config=self.tasks_config["website_audit_task"],  # type: ignore[index]
            output_file="website_audit.md",
        )

    @task
    def competitor_analysis_task(self) -> Task:
        return Task(
            name="competitor_analysis_task",
            config=self.tasks_config["competitor_analysis_task"],  # type: ignore[index]
            output_file="competitor_analysis.md",
        )

    @task
    def landing_page_task(self) -> Task:
        return Task(
            name="landing_page_task",
            config=self.tasks_config["landing_page_task"],  # type: ignore[index]
            output_file="landing_pages.md",
        )

    @task
    def marketing_recommendation_task(self) -> Task:
        return Task(
            name="marketing_recommendation_task",
            config=self.tasks_config["marketing_recommendation_task"],  # type: ignore[index]
            output_file="marketing_plan.md",
        )

    @task
    def proposal_task(self) -> Task:
        return Task(
            name="proposal_task",
            config=self.tasks_config["proposal_task"],  # type: ignore[index]
            output_file="proposal_canonical.md",
        )

    @task
    def proposal_localization_task(self) -> Task:
        return Task(
            name="proposal_localization_task",
            config=self.tasks_config["proposal_localization_task"],  # type: ignore[index]
            output_file="proposal.md",
        )

    @task
    def email_outreach_task(self) -> Task:
        return Task(
            name="email_outreach_task",
            config=self.tasks_config["email_outreach_task"],  # type: ignore[index]
            output_file="outreach_emails_canonical.md",
        )

    @task
    def email_localization_task(self) -> Task:
        return Task(
            name="email_localization_task",
            config=self.tasks_config["email_localization_task"],  # type: ignore[index]
            output_file="outreach_emails.md",
        )

    @task
    def notion_logging_task(self) -> Task:
        return Task(
            name="notion_logging_task",
            config=self.tasks_config["notion_logging_task"],  # type: ignore[index]
            output_file="notion_log_summary.md",
        )

    @crew
    def crew(self) -> Crew:
        """Creates the SalesFactory crew"""

        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
