Check out ~/workspace/token_world/token_world/llm/xplore

Its basically an AI text based RPG.

I want to rebuild it but with a clean maintainable architecture.

Normally I would not try to reinvent the wheel and just use some kind of agent CLI like goose which supports custom inference endpoints. But the problem is that I want it to work with very tiny models that can even run on a local machine, which means that they will begin to struggle as the context grows, or a series of tool calls are required or even basic instructions.
Assume the model is a thinking model.

As a result, the turns needs to be driven programatically. I'll elaborate on this in a second.

There are a few things I want to do differently this time.

I am imagining a games/ and saves/ folder.
A game consists of a world.md, characters/ each with their own persona files e.g. Tom.md, a storyline/ with numbered chapters e.g. "01-plane-crash-on-the-island.md", and most importantly a system prompt file specialized for that game, etc.
And a game-creation agent can help here.

I want to support multiple AI characters.

I'm trying to think about all the ways in which to make the system robust to smaller models. The main thing I can think of is to have specialized agents for each character, to simplify the instructions by only focusing on one thing at a time, and injecting context (memory file content, special reminders, etc) in the latest part of the conversation similar to Goose's MOIM message file https://block.github.io/goose/docs/guides/using-persistent-instructions.md . Do you have other ideas?

A new-game script that essentially just copies a game into the saves/ folder with a new game.
A save is basically a superset of a game folder which additionally has a memory/ folder consisting of a memory md for each character and for the narrator that constantly evolves over time.
Also see ~/workspace/nottheact/saves/playtest-001/ as an example game another agent created, but it needs to be simplified significantly to not confuse smaller models.

Regarding programatically driving turns, how would you design this?
What should the flow look like given a user input?
Maybe first a narrator agent adds a brief naration and then decides which characters need to respond. The narrator must be prompted to think about the users input and guide the conversation based on the storyline.
This then delegates to the respective character agents that generate their response.
After all the characters respond, we then delegate to dedicated agents that manage the updates to the memory of each respective agent's memory file. Should the memory be more structured than MD? xplore tackled the memory problem through an list of up to 5 goals or responsibilities (I don't remember what they were called) each classified as short term, or long term. The agent needed to provide justification grounded in the conversation on when a goal was complete and can be hidden and separately also prompted if any additional goal needed to be added. This worked well for small models since the model basically just makes one decision at a time, but the problem in practice was that the models often made the wrong decision, deleting goals that were clearly not complete, creating goals that were almost the same as already active goals, etc.
The agent responses are all brought together and shown to the user for the next turn.

Another important requirement is to make the game versioned so that the user can undo an unlimited number of times. This is especially helpful for development. Finally, whatever approach we take, we need to make sure the design is such that you have the tools you need or can easily create the tools you need to play test things autonomously.

Is streamlit the easiest way to show the UI? Is there something else that might work out of the box to show thinking, streaming tokens, and maybe even tool use?

Can you do all the necessary research on potential python frameworks for this project, xplore, etc and plan the whole project?
How to manage the chat history, chat summarization to work with a small context window, etc?

I want you to take lead on this project, think creatively and logically, and ask me clarifying questions as needed like an experienced software architect who anticipates issues would.
I want you to create a docs/plans folder with phase01-xxx.md and so on md files for how you will achieve this in detail.
