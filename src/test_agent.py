import os
import openlit
from openhands.sdk import LLM, Agent, Conversation
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool

# Wire OpenLIT telemetry — one line
#openlit.init(
 #   otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
 #   api_key=os.getenv("OPENLIT_API_KEY"),
#)

openlit.init(
    otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
)


llm = LLM(
    model=os.getenv("LLM_MODEL"),
    api_key=os.getenv("LLM_API_KEY"),
)

#agent = Agent(llm=llm, tools=[TerminalTool(), FileEditorTool()])


from openhands.sdk.tool import Tool

agent = Agent(
    llm=llm,
    tools=[
        Tool(name="TerminalTool"),
        Tool(name="FileEditorTool"),
    ],
)



conversation = Conversation(agent=agent, workspace=os.getcwd())
conversation.send_message(
    "List the files in the current directory and write a one-line summary to SUMMARY.txt"
)
conversation.run()
print("Done — check http://localhost:3000 for traces")
