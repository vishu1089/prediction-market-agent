import getpass
from decimal import Decimal

from prediction_market_agent_tooling.config import APIKeys
from prediction_market_agent_tooling.deploy.agent import DeployableAgent
from prediction_market_agent_tooling.deploy.constants import OWNER_KEY
from prediction_market_agent_tooling.gtypes import SecretStr, private_key_type
from prediction_market_agent_tooling.markets.agent_market import AgentMarket
from prediction_market_agent_tooling.markets.data_models import BetAmount, Currency
from prediction_market_agent_tooling.markets.markets import MarketType
from prediction_market_agent_tooling.tools.utils import (
    get_current_git_commit_sha,
    get_current_git_url,
)
from prediction_market_agent_tooling.tools.web3_utils import verify_address

from prediction_market_agent.agents.known_outcome_agent.known_outcome_agent import (
    Result,
    get_known_outcome,
    has_question_event_happened_in_the_past,
)


def market_is_saturated(market: AgentMarket) -> bool:
    return market.p_yes > 0.95 or market.p_no > 0.95


class DeployableKnownOutcomeAgent(DeployableAgent):
    model = "gpt-4-1106-preview"

    def load(self) -> None:
        self.markets_with_known_outcomes: dict[str, Result] = {}

    def pick_markets(self, markets: list[AgentMarket]) -> list[AgentMarket]:
        picked_markets: list[AgentMarket] = []
        for market in markets:
            # Assume very high probability markets are already known, and have
            # been correctly bet on, and therefore the value of betting on them
            # is low.
            print(f"Looking at market {market.id=} {market.question=}")
            if not market_is_saturated(
                market=market
            ) and has_question_event_happened_in_the_past(
                model=self.model, question=market.question
            ):
                print(f"Predicting market {market.id=} {market.question=}")
                try:
                    answer = get_known_outcome(
                        model=self.model,
                        question=market.question,
                        max_tries=3,
                    )
                except Exception as e:
                    print(
                        f"Error: Failed to predict market {market.id=} {market.question=}: {e}"
                    )
                    continue
                if answer.has_known_outcome():
                    print(
                        f"Picking market {market.id=} {market.question=} with answer {answer.result=}"
                    )
                    picked_markets.append(market)
                    self.markets_with_known_outcomes[market.id] = answer.result

                    # Return as soon as we have picked a market, because otherwise it will take too long and we will run out of time in GCP Function (540s timeout)
                    # TODO: After PMAT is updated in this repository, we can return `None` in `answer_binary_market` method and PMAT won't place the bet.
                    # So we can move this logic out of `pick_markets` into `answer_binary_market`, and simply process as many bets as we have time for.
                    return picked_markets

            else:
                print(
                    f"Skipping market {market.id=} {market.question=}, because it is already saturated."
                )

        return picked_markets

    def answer_binary_market(self, market: AgentMarket) -> bool:
        # The answer has already been determined in `pick_markets` so we just
        # return it here.
        return self.markets_with_known_outcomes[market.id].to_boolean()

    def calculate_bet_amount(self, answer: bool, market: AgentMarket) -> BetAmount:
        if market.currency == Currency.xDai:
            return BetAmount(amount=Decimal(0.1), currency=Currency.xDai)
        else:
            raise NotImplementedError("This agent only supports xDai markets")


if __name__ == "__main__":
    agent = DeployableKnownOutcomeAgent()
    agent.deploy_gcp(
        repository=f"git+{get_current_git_url()}@{get_current_git_commit_sha()}",
        market_type=MarketType.OMEN,
        labels={OWNER_KEY: getpass.getuser()},
        secrets={
            "TAVILY_API_KEY": "GNOSIS_AI_TAVILY_API_KEY:latest",
        },
        memory=1024,
        api_keys=APIKeys(
            BET_FROM_ADDRESS=verify_address(
                "0xb611A9f02B318339049264c7a66ac3401281cc3c"
            ),
            BET_FROM_PRIVATE_KEY=private_key_type("EVAN_OMEN_BETTER_0_PKEY:latest"),
            OPENAI_API_KEY=SecretStr("EVAN_OPENAI_API_KEY:latest"),
            MANIFOLD_API_KEY=None,
        ),
        cron_schedule="0 */12 * * *",
        timeout=540,
    )
