import typing as t

from crewai import Agent, Crew, Process, Task
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from loguru import logger
from prediction_market_agent_tooling.tools.parallelism import par_generator
from prediction_market_agent_tooling.tools.utils import utcnow
from pydantic import BaseModel

from prediction_market_agent.agents.think_thoroughly_agent.prompts import (
    CREATE_HYPOTHETICAL_SCENARIOS_FROM_SCENARIO_PROMPT,
    CREATE_REQUIRED_CONDITIONS_PROMPT,
    FINAL_DECISION_PROMPT,
    LIST_OF_SCENARIOS_OUTPUT,
    PROBABILITY_CLASS_OUTPUT,
    PROBABILITY_FOR_ONE_OUTCOME_PROMPT,
    RESEARCH_OUTCOME_OUTPUT,
    RESEARCH_OUTCOME_PROMPT,
)
from prediction_market_agent.tools.custom_crewai_tools import TavilyDevTool
from prediction_market_agent.utils import APIKeys


class Scenarios(BaseModel):
    scenarios: list[str]


class ProbabilityOutput(BaseModel):
    reasoning: str
    decision: t.Literal["y", "n"] | None
    p_yes: float
    p_no: float
    confidence: float


class CrewAIAgentSubquestions:
    def __init__(self, model: str) -> None:
        self.model = model

    def _get_current_date(self) -> str:
        return utcnow().strftime("%Y-%m-%d")

    def _get_researcher(self) -> Agent:
        return Agent(
            role="Research Analyst",
            goal="Research and report on some future event, giving high quality and nuanced analysis",
            backstory=f"Current date is {self._get_current_date()}. You are a senior research analyst who is adept at researching and reporting on future events.",
            verbose=True,
            allow_delegation=False,
            tools=[self._build_tavily_search()],
            llm=self._build_llm(),
        )

    def _get_predictor(self) -> Agent:
        return Agent(
            role="Professional Gambler",
            goal="Predict, based on some research you are presented with, whether or not a given event will occur",
            backstory=f"Current date is {self._get_current_date()}. You are a professional gambler who is adept at predicting and betting on the outcomes of future events.",
            verbose=True,
            allow_delegation=False,
            llm=self._build_llm(),
        )

    def _build_tavily_search(self) -> TavilyDevTool:
        return TavilyDevTool()

    def _build_llm(self) -> BaseChatModel:
        keys = APIKeys()
        llm = ChatOpenAI(
            model=self.model,
            api_key=keys.openai_api_key.get_secret_value(),
            temperature=0.0,
        )
        return llm

    def get_required_conditions(self, question: str) -> Scenarios:
        researcher = self._get_researcher()

        create_required_conditions = Task(
            description=CREATE_REQUIRED_CONDITIONS_PROMPT,
            expected_output=LIST_OF_SCENARIOS_OUTPUT,
            output_json=Scenarios,
            agent=researcher,
        )

        report_crew = Crew(
            agents=[researcher],
            tasks=[create_required_conditions],
        )
        result = report_crew.kickoff(inputs={"scenario": question, "n_scenarios": 3})
        scenarios = Scenarios.model_validate_json(result)

        logger.info(f"Created conditional scenarios: {scenarios.scenarios}")
        return scenarios

    def get_hypohetical_scenarios(self, question: str) -> Scenarios:
        researcher = self._get_researcher()

        create_scenarios_task = Task(
            description=CREATE_HYPOTHETICAL_SCENARIOS_FROM_SCENARIO_PROMPT,
            expected_output=LIST_OF_SCENARIOS_OUTPUT,
            output_json=Scenarios,
            agent=researcher,
        )

        report_crew = Crew(
            agents=[researcher],
            tasks=[create_scenarios_task],
        )
        result = report_crew.kickoff(inputs={"scenario": question, "n_scenarios": 5})
        scenarios = Scenarios.model_validate_json(result)

        # Add the original question if it wasn't included by the LLM.
        if question not in scenarios.scenarios:
            scenarios.scenarios.append(question)

        logger.info(f"Created possible hypothetical scenarios: {scenarios.scenarios}")
        return scenarios

    def generate_prediction_for_one_outcome(
        self, sentence: str
    ) -> ProbabilityOutput | None:
        researcher = self._get_researcher()
        predictor = self._get_predictor()

        task_research_one_outcome = Task(
            description=RESEARCH_OUTCOME_PROMPT,
            agent=researcher,
            expected_output=RESEARCH_OUTCOME_OUTPUT,
        )
        task_create_probability_for_one_outcome = Task(
            description=PROBABILITY_FOR_ONE_OUTCOME_PROMPT,
            expected_output=PROBABILITY_CLASS_OUTPUT,
            agent=predictor,
            output_json=ProbabilityOutput,
            context=[task_research_one_outcome],
        )
        crew = Crew(
            agents=[researcher, predictor],
            tasks=[task_research_one_outcome, task_create_probability_for_one_outcome],
            verbose=2,
            process=Process.sequential,
        )

        result = crew.kickoff(inputs={"sentence": sentence})
        try:
            output = ProbabilityOutput.model_validate_json(result)
            return output
        except ValueError as e:
            logger.error(
                f"Could not parse the result ('{result}') as ProbabilityOutput because of {e}"
            )
            return None

    def generate_final_decision(
        self, scenarios_with_probabilities: list[t.Tuple[str, ProbabilityOutput]]
    ) -> ProbabilityOutput:
        predictor = self._get_predictor()

        task_final_decision = Task(
            description=FINAL_DECISION_PROMPT,
            agent=predictor,
            expected_output=PROBABILITY_CLASS_OUTPUT,
            output_json=ProbabilityOutput,
        )

        crew = Crew(
            agents=[predictor],
            tasks=[task_final_decision],
            verbose=2,
        )

        crew.kickoff(
            inputs={
                "scenarios_with_probabilities": [
                    (i[0], i[1].model_dump()) for i in scenarios_with_probabilities
                ],
                "number_of_scenarios": len(scenarios_with_probabilities),
                "scenario_to_assess": scenarios_with_probabilities[0][0],
            }
        )
        output = ProbabilityOutput.model_validate_json(
            task_final_decision.output.raw_output
        )
        logger.info(
            f"The final prediction is '{output.decision}', with p_yes={output.p_yes}, p_no={output.p_no}, and confidence={output.confidence}"
        )
        return output

    def answer_binary_market(self, question: str) -> ProbabilityOutput | None:
        hypothetical_scenarios = self.get_hypohetical_scenarios(question)
        conditional_scenarios = self.get_required_conditions(question)

        sub_predictions = par_generator(
            hypothetical_scenarios.scenarios + conditional_scenarios.scenarios,
            lambda x: (x, self.generate_prediction_for_one_outcome(x)),
        )

        outcomes_with_probs = []
        for scenario, prediction in sub_predictions:
            if prediction is None:
                continue
            outcomes_with_probs.append((scenario, prediction))
            logger.info(
                f"'{scenario}' has prediction {prediction.p_yes * 100:.2f}% chance of being True, because: '{prediction.reasoning}'"
            )

        final_answer = (
            self.generate_final_decision(outcomes_with_probs)
            if outcomes_with_probs
            else None
        )
        return final_answer
