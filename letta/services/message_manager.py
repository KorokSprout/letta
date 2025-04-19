import json
from typing import List, Optional, Sequence

from sqlalchemy import delete, exists, func, select, text

from letta.log import get_logger
from letta.orm.agent import Agent as AgentModel
from letta.orm.errors import NoResultFound
from letta.orm.message import Message as MessageModel
from letta.schemas.enums import MessageRole
from letta.schemas.letta_message import LettaMessageUpdateUnion
from letta.schemas.message import Message as PydanticMessage
from letta.schemas.message import MessageUpdate
from letta.schemas.user import User as PydanticUser
from letta.utils import enforce_types

logger = get_logger(__name__)


class MessageManager:
    """Manager class to handle business logic related to Messages."""

    def __init__(self):
        from letta.server.db import db_context

        self.session_maker = db_context

    @enforce_types
    def get_message_by_id(self, message_id: str, actor: PydanticUser) -> Optional[PydanticMessage]:
        """Fetch a message by ID."""
        with self.session_maker() as session:
            try:
                message = MessageModel.read(db_session=session, identifier=message_id, actor=actor)
                return message.to_pydantic()
            except NoResultFound:
                return None

    @enforce_types
    def get_messages_by_ids(self, message_ids: List[str], actor: PydanticUser) -> List[PydanticMessage]:
        """Fetch messages by ID and return them in the requested order."""
        with self.session_maker() as session:
            results = MessageModel.list(db_session=session, id=message_ids, organization_id=actor.organization_id, limit=len(message_ids))

            if len(results) != len(message_ids):
                logger.warning(
                    f"Expected {len(message_ids)} messages, but found {len(results)}. Missing ids={set(message_ids) - set([r.id for r in results])}"
                )

            # Sort results directly based on message_ids
            result_dict = {msg.id: msg.to_pydantic() for msg in results}
            return list(filter(lambda x: x is not None, [result_dict.get(msg_id, None) for msg_id in message_ids]))

    @enforce_types
    def create_message(self, pydantic_msg: PydanticMessage, actor: PydanticUser) -> PydanticMessage:
        """Create a new message."""
        with self.session_maker() as session:
            # Set the organization id of the Pydantic message
            pydantic_msg.organization_id = actor.organization_id
            msg_data = pydantic_msg.model_dump(to_orm=True)
            msg = MessageModel(**msg_data)
            msg.create(session, actor=actor)  # Persist to database
            return msg.to_pydantic()

    @enforce_types
    def create_many_messages(self, pydantic_msgs: List[PydanticMessage], actor: PydanticUser) -> List[PydanticMessage]:
        """
        Create multiple messages in a single database transaction.

        Args:
            pydantic_msgs: List of Pydantic message models to create
            actor: User performing the action

        Returns:
            List of created Pydantic message models
        """
        if not pydantic_msgs:
            return []

        # Create ORM model instances for all messages
        orm_messages = []
        for pydantic_msg in pydantic_msgs:
            # Set the organization id of the Pydantic message
            pydantic_msg.organization_id = actor.organization_id
            msg_data = pydantic_msg.model_dump(to_orm=True)
            orm_messages.append(MessageModel(**msg_data))

        # Use the batch_create method for efficient creation
        with self.session_maker() as session:
            created_messages = MessageModel.batch_create(orm_messages, session, actor=actor)

            # Convert back to Pydantic models
            return [msg.to_pydantic() for msg in created_messages]

    @enforce_types
    def update_message_by_letta_message(
        self, message_id: str, letta_message_update: LettaMessageUpdateUnion, actor: PydanticUser
    ) -> PydanticMessage:
        """
        Updated the underlying messages table giving an update specified to the user-facing LettaMessage
        """
        message = self.get_message_by_id(message_id=message_id, actor=actor)
        if letta_message_update.message_type == "assistant_message":
            # modify the tool call for send_message
            # TODO: fix this if we add parallel tool calls
            # TODO: note this only works if the AssistantMessage is generated by the standard send_message
            assert (
                message.tool_calls[0].function.name == "send_message"
            ), f"Expected the first tool call to be send_message, but got {message.tool_calls[0].function.name}"
            original_args = json.loads(message.tool_calls[0].function.arguments)
            original_args["message"] = letta_message_update.content  # override the assistant message
            update_tool_call = message.tool_calls[0].__deepcopy__()
            update_tool_call.function.arguments = json.dumps(original_args)

            update_message = MessageUpdate(tool_calls=[update_tool_call])
        elif letta_message_update.message_type == "reasoning_message":
            update_message = MessageUpdate(content=letta_message_update.reasoning)
        elif letta_message_update.message_type == "user_message" or letta_message_update.message_type == "system_message":
            update_message = MessageUpdate(content=letta_message_update.content)
        else:
            raise ValueError(f"Unsupported message type for modification: {letta_message_update.message_type}")

        message = self.update_message_by_id(message_id=message_id, message_update=update_message, actor=actor)

        # convert back to LettaMessage
        for letta_msg in message.to_letta_message(use_assistant_message=True):
            if letta_msg.message_type == letta_message_update.message_type:
                return letta_msg

        # raise error if message type got modified
        raise ValueError(f"Message type got modified: {letta_message_update.message_type}")

    @enforce_types
    def update_message_by_letta_message(
        self, message_id: str, letta_message_update: LettaMessageUpdateUnion, actor: PydanticUser
    ) -> PydanticMessage:
        """
        Updated the underlying messages table giving an update specified to the user-facing LettaMessage
        """
        message = self.get_message_by_id(message_id=message_id, actor=actor)
        if letta_message_update.message_type == "assistant_message":
            # modify the tool call for send_message
            # TODO: fix this if we add parallel tool calls
            # TODO: note this only works if the AssistantMessage is generated by the standard send_message
            assert (
                message.tool_calls[0].function.name == "send_message"
            ), f"Expected the first tool call to be send_message, but got {message.tool_calls[0].function.name}"
            original_args = json.loads(message.tool_calls[0].function.arguments)
            original_args["message"] = letta_message_update.content  # override the assistant message
            update_tool_call = message.tool_calls[0].__deepcopy__()
            update_tool_call.function.arguments = json.dumps(original_args)

            update_message = MessageUpdate(tool_calls=[update_tool_call])
        elif letta_message_update.message_type == "reasoning_message":
            update_message = MessageUpdate(content=letta_message_update.reasoning)
        elif letta_message_update.message_type == "user_message" or letta_message_update.message_type == "system_message":
            update_message = MessageUpdate(content=letta_message_update.content)
        else:
            raise ValueError(f"Unsupported message type for modification: {letta_message_update.message_type}")

        message = self.update_message_by_id(message_id=message_id, message_update=update_message, actor=actor)

        # convert back to LettaMessage
        for letta_msg in message.to_letta_message(use_assistant_message=True):
            if letta_msg.message_type == letta_message_update.message_type:
                return letta_msg

        # raise error if message type got modified
        raise ValueError(f"Message type got modified: {letta_message_update.message_type}")

    @enforce_types
    def update_message_by_id(self, message_id: str, message_update: MessageUpdate, actor: PydanticUser) -> PydanticMessage:
        """
        Updates an existing record in the database with values from the provided record object.
        """
        with self.session_maker() as session:
            # Fetch existing message from database
            message = MessageModel.read(
                db_session=session,
                identifier=message_id,
                actor=actor,
            )

            # Some safety checks specific to messages
            if message_update.tool_calls and message.role != MessageRole.assistant:
                raise ValueError(
                    f"Tool calls {message_update.tool_calls} can only be added to assistant messages. Message {message_id} has role {message.role}."
                )
            if message_update.tool_call_id and message.role != MessageRole.tool:
                raise ValueError(
                    f"Tool call IDs {message_update.tool_call_id} can only be added to tool messages. Message {message_id} has role {message.role}."
                )

            # get update dictionary
            update_data = message_update.model_dump(to_orm=True, exclude_unset=True, exclude_none=True)
            # Remove redundant update fields
            update_data = {key: value for key, value in update_data.items() if getattr(message, key) != value}

            for key, value in update_data.items():
                setattr(message, key, value)
            message.update(db_session=session, actor=actor)

            return message.to_pydantic()

    @enforce_types
    def delete_message_by_id(self, message_id: str, actor: PydanticUser) -> bool:
        """Delete a message."""
        with self.session_maker() as session:
            try:
                msg = MessageModel.read(
                    db_session=session,
                    identifier=message_id,
                    actor=actor,
                )
                msg.hard_delete(session, actor=actor)
            except NoResultFound:
                raise ValueError(f"Message with id {message_id} not found.")

    @enforce_types
    def size(
        self,
        actor: PydanticUser,
        role: Optional[MessageRole] = None,
        agent_id: Optional[str] = None,
    ) -> int:
        """Get the total count of messages with optional filters.

        Args:
            actor: The user requesting the count
            role: The role of the message
        """
        with self.session_maker() as session:
            return MessageModel.size(db_session=session, actor=actor, role=role, agent_id=agent_id)

    @enforce_types
    def list_user_messages_for_agent(
        self,
        agent_id: str,
        actor: PydanticUser,
        after: Optional[str] = None,
        before: Optional[str] = None,
        query_text: Optional[str] = None,
        limit: Optional[int] = 50,
        ascending: bool = True,
    ) -> List[PydanticMessage]:
        return self.list_messages_for_agent(
            agent_id=agent_id,
            actor=actor,
            after=after,
            before=before,
            query_text=query_text,
            roles=[MessageRole.user],
            limit=limit,
            ascending=ascending,
        )

    @enforce_types
    def list_messages_for_agent(
        self,
        agent_id: str,
        actor: PydanticUser,
        after: Optional[str] = None,
        before: Optional[str] = None,
        query_text: Optional[str] = None,
        roles: Optional[Sequence[MessageRole]] = None,
        limit: Optional[int] = 50,
        ascending: bool = True,
        group_id: Optional[str] = None,
    ) -> List[PydanticMessage]:
        """
        Most performant query to list messages for an agent by directly querying the Message table.

        This function filters by the agent_id (leveraging the index on messages.agent_id)
        and applies pagination using sequence_id as the cursor.
        If query_text is provided, it will filter messages whose text content partially matches the query.
        If role is provided, it will filter messages by the specified role.

        Args:
            agent_id: The ID of the agent whose messages are queried.
            actor: The user performing the action (used for permission checks).
            after: A message ID; if provided, only messages *after* this message (by sequence_id) are returned.
            before: A message ID; if provided, only messages *before* this message (by sequence_id) are returned.
            query_text: Optional string to partially match the message text content.
            roles: Optional MessageRole to filter messages by role.
            limit: Maximum number of messages to return.
            ascending: If True, sort by sequence_id ascending; if False, sort descending.
            group_id: Optional group ID to filter messages by group_id.

        Returns:
            List[PydanticMessage]: A list of messages (converted via .to_pydantic()).

        Raises:
            NoResultFound: If the provided after/before message IDs do not exist.
        """

        with self.session_maker() as session:
            # Permission check: raise if the agent doesn't exist or actor is not allowed.
            AgentModel.read(db_session=session, identifier=agent_id, actor=actor)

            # Build a query that directly filters the Message table by agent_id.
            query = session.query(MessageModel).filter(MessageModel.agent_id == agent_id)

            # If group_id is provided, filter messages by group_id.
            if group_id:
                query = query.filter(MessageModel.group_id == group_id)

            # If query_text is provided, filter messages using subquery + json_array_elements.
            if query_text:
                content_element = func.json_array_elements(MessageModel.content).alias("content_element")
                query = query.filter(
                    exists(
                        select(1)
                        .select_from(content_element)
                        .where(text("content_element->>'type' = 'text' AND content_element->>'text' ILIKE :query_text"))
                        .params(query_text=f"%{query_text}%")
                    )
                )

            # If role(s) are provided, filter messages by those roles.
            if roles:
                role_values = [r.value for r in roles]
                query = query.filter(MessageModel.role.in_(role_values))

            # Apply 'after' pagination if specified.
            if after:
                after_ref = session.query(MessageModel.sequence_id).filter(MessageModel.id == after).one_or_none()
                if not after_ref:
                    raise NoResultFound(f"No message found with id '{after}' for agent '{agent_id}'.")
                # Filter out any messages with a sequence_id <= after_ref.sequence_id
                query = query.filter(MessageModel.sequence_id > after_ref.sequence_id)

            # Apply 'before' pagination if specified.
            if before:
                before_ref = session.query(MessageModel.sequence_id).filter(MessageModel.id == before).one_or_none()
                if not before_ref:
                    raise NoResultFound(f"No message found with id '{before}' for agent '{agent_id}'.")
                # Filter out any messages with a sequence_id >= before_ref.sequence_id
                query = query.filter(MessageModel.sequence_id < before_ref.sequence_id)

            # Apply ordering based on the ascending flag.
            if ascending:
                query = query.order_by(MessageModel.sequence_id.asc())
            else:
                query = query.order_by(MessageModel.sequence_id.desc())

            # Limit the number of results.
            query = query.limit(limit)

            # Execute and convert each Message to its Pydantic representation.
            results = query.all()
            return [msg.to_pydantic() for msg in results]

    @enforce_types
    def delete_all_messages_for_agent(self, agent_id: str, actor: PydanticUser) -> int:
        """
        Efficiently deletes all messages associated with a given agent_id,
        while enforcing permission checks and avoiding any ORM‑level loads.
        """
        with self.session_maker() as session:
            # 1) verify the agent exists and the actor has access
            AgentModel.read(db_session=session, identifier=agent_id, actor=actor)

            # 2) issue a CORE DELETE against the mapped class
            stmt = (
                delete(MessageModel).where(MessageModel.agent_id == agent_id).where(MessageModel.organization_id == actor.organization_id)
            )
            result = session.execute(stmt)

            # 3) commit once
            session.commit()

            # 4) return the number of rows deleted
            return result.rowcount
