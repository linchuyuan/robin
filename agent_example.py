
# To use these skills, you would typically do something like this:

from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI
from skills import tools
import os

# You would need an OPENAI_API_KEY environment variable set
# llm = ChatOpenAI(temperature=0, model="gpt-4")
# agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS, verbose=True)

# agent.run("What is the latest news on AAPL and how has it performed over the last week?")
