# tanomu

A personal agent that lives in Feishu, first used by one person and gradually rolled out to the team. It chats, searches the web, generates images, and pushes tech blog posts to Feishu groups.

## Conversation

**Private Conversation**:
A one-on-one conversation between a single User and tanomu. Each User's context is separate.
_Avoid_: DM session, single chat

**Group Conversation**:
The conversation in a Feishu group that tanomu has joined. Its context is shared by all members of the group.
_Avoid_: group session, channel

**Memory**:
Information tanomu retains long-term within one Conversation (about a person or a group). A Memory belongs only to the Conversation it came from.
_Avoid_: context, history, profile

**Persona**:
tanomu's fixed identity, personality, and way of speaking, consistent across all Conversations.
_Avoid_: role, system prompt, character

## Administration

**User**:
A person who can talk to tanomu.
_Avoid_: member, customer, account

**Capability**:
A kind of function tanomu offers, such as chat, summarization, image generation, web search, or embedding. Each Capability is bound to its own model or service.
_Avoid_: skill, feature module

**Provider**:
An API endpoint that serves models or search, identified by its address, key, and protocol type.
_Avoid_: channel, vendor, supplier

## Software Factory

**Factory Agent**:
A model-driven participant in the software factory that performs an implementation or review role without deployment authority.
_Avoid_: bot, autonomous maintainer

**Provider Preflight**:
An operational check that a Provider works for a Factory Agent role. It is not a stage in the software factory task lifecycle.
_Avoid_: smoke task, implementation round

**Run Evidence**:
The retained record of a Factory Agent run and its outcomes, used for human diagnosis. It does not authorize publication or delivery.
_Avoid_: trusted transcript, approval record

## Blog Digest

**Feed**:
An external source from which tanomu periodically fetches tech articles.
_Avoid_: source, channel, subscription

**Digest Rule**:
The digest configuration for one target group: its Feeds, Topic Preference, and schedule. Each group has at most one Digest Rule.
_Avoid_: subscription, task, job

**Topic Preference**:
The part of a Digest Rule that describes which tech topics the group cares about; the model uses it to pick articles.
_Avoid_: tags, keywords, filter

**Digest**:
One run of a Digest Rule: pick articles from its Feeds that match the Topic Preference, summarize them, and post them to the target group.
_Avoid_: daily report, newsletter, broadcast
