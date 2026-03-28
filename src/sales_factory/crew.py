from typing import List

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


@CrewBase
class SalesFactory:
    """SalesFactory crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    @agent
    def lead_finder(self) -> Agent:
        return Agent(
            config=self.agents_config["lead_finder"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def website_auditor(self) -> Agent:
        tools = [_scrape_tool] if _scrape_tool else []
        return Agent(
            config=self.agents_config["website_auditor"],  # type: ignore[index]
            tools=[t for t in tools if t is not None],
            verbose=True,
        )

    @agent
    def competitor_analyst(self) -> Agent:
        tools = [_scrape_tool] if _scrape_tool else []
        return Agent(
            config=self.agents_config["competitor_analyst"],  # type: ignore[index]
            tools=[t for t in tools if t is not None],
            verbose=True,
        )

    @agent
    def landing_page_builder(self) -> Agent:
        return Agent(
            config=self.agents_config["landing_page_builder"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def marketing_strategist(self) -> Agent:
        return Agent(
            config=self.agents_config["marketing_strategist"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def proposal_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["proposal_writer"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def email_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["email_writer"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def notion_logger(self) -> Agent:
        return Agent(
            config=self.agents_config["notion_logger"],  # type: ignore[index]
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
            output_file="proposal.md",
        )

    @task
    def email_outreach_task(self) -> Task:
        return Task(
            name="email_outreach_task",
            config=self.tasks_config["email_outreach_task"],  # type: ignore[index]
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
