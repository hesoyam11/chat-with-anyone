from aiohttp import web
from aiohttp_apispec import docs, request_schema, response_schema
from aiohttp_cors import CorsViewMixin
from asyncpg import ForeignKeyViolationError, UniqueViolationError
from marshmallow import Schema, fields, validate
from sqlalchemy import and_

from ..db import db
from ..decorators import token_and_active_required
from ..models.group_membership import GroupMembership
from ..models.group_message import GroupMessage
from ..models.group_room import GroupRoom
from ..models.user import User


class ChatRequestSchema(Schema):
    name = fields.Str(
        validate=validate.Length(max=200), required=True
    )


class ChatResponseSchema(Schema):
    id = fields.Int()
    name = fields.Str(
        validate=validate.Length(max=200), required=True
    )


class AddUserRequestSchema(Schema):
    user_id = fields.Int()


class MessageRequestSchema(Schema):
    text = fields.Str(validate=validate.Length(max=500), required=True)


class MessageResponseSchema(Schema):
    id = fields.Int()
    text = fields.Str(validate=validate.Length(max=500), required=True)
    created_at = fields.Str()
    username = fields.Str(validate=validate.Length(max=40), required=True)


class Chats(web.View, CorsViewMixin):
    @docs(
        tags=['Chats'],
        summary='Create a new chat.',
        parameters=[
            {
                'in': 'header',
                'name': 'Authorization',
                'schema': {'type': 'string'},
                'required': 'true'
            }
        ]
    )
    @request_schema(ChatRequestSchema(strict=True))
    @token_and_active_required
    async def post(self):
        data = await self.request.json()
        user = self.request["user"]
        created_chat = await GroupRoom.create(
            name=data['name']
        )

        await GroupMembership.create(
            room_id=created_chat.id,
            user_id=user.id
        )

        return web.json_response(status=201)

    @docs(
        tags=['Chats'],
        summary='Fetch list of chats.',
        parameters=[
            {
                'in': 'header',
                'name': 'Authorization',
                'schema': {'type': 'string'},
                'required': 'true'
            },
            {
                'in': 'query',
                'name': 'name',
                'schema': {'type': 'string'},
            },
            {
                'in': 'query',
                'name': 'page',
                'schema': {'type': 'integer'},
            },
            {
                'in': 'query',
                'name': 'page_size',
                'schema': {'type': 'integer'},
            }
        ]
    )
    @response_schema(ChatResponseSchema(many=True), 200)
    @token_and_active_required
    async def get(self):
        query = self.request.query

        try:
            page = int(query.get('page', 1))
            page_size = int(query.get('page_size', 10))
        except ValueError:
            page = 1
            page_size = 10

        if page > 50:
            page = 50

        if page < 1:
            page = 1

        if page_size > 50:
            page_size = 50

        if page_size < 1:
            page_size = 1

        name = query.get('name')

        condition = []

        if name:
            condition.append(GroupRoom.name.ilike(f'%{name}%'))

        chats = await GroupRoom.query.where(and_(*condition)) \
            .limit(page_size).offset(page * page_size - page_size).gino.all()

        return web.json_response(
            ChatResponseSchema().dump(
                [chat.to_dict() for chat in chats],
                many=True
            ).data)


class ChatUserList(web.View, CorsViewMixin):
    @docs(
        tags=['Chats'],
        summary='Add user into chat.',
        parameters=[{
            'in': 'header',
            'name': 'Authorization',
            'schema': {'type': 'string'},
            'required': 'true'
        }]
    )
    @request_schema(AddUserRequestSchema(strict=True))
    @token_and_active_required
    async def post(self):
        user = self.request["user"]
        request_chat_id = int(self.request.match_info.get('chat_id'))
        request_chat = await GroupRoom.get(request_chat_id)

        if request_chat is None:
            return web.json_response(
                {'message': f'Chat with ID "{request_chat_id}" was not found'},
                status=404
            )

        user_id = self.request.get('data', {}).get('user_id')

        if user.id != user_id:
            user_group = await GroupMembership.query.where(
                and_(
                    GroupMembership.user_id == user.id,
                    GroupMembership.room_id == request_chat_id
                )
            ).gino.first()

            if user_group is None:
                message = 'You have not been assigned with provided chat'

                return web.json_response(
                    {'message': message},
                    status=403
                )

        try:
            await GroupMembership.create(
                room_id=request_chat_id,
                user_id=user_id
            )
        except ForeignKeyViolationError:
            return web.json_response(
                {"message": "Provided chat_id or user_id is invalid"},
                status=400
            )
        except UniqueViolationError:
            return web.json_response(
                {"message": f'User with ID "{user_id}" already exists'},
                status=400
            )

        return web.json_response(status=201)


class ChatUserDetails(web.View, CorsViewMixin):
    @docs(
        tags=['Chats'],
        summary='Remove a user from a chat.',
        parameters=[{
            'in': 'header',
            'name': 'Authorization',
            'schema': {'type': 'string'},
            'required': 'true'
        }]
    )
    @token_and_active_required
    async def delete(self):
        user = self.request["user"]
        request_user_id = int(self.request.match_info.get('user_id'))
        request_chat_id = int(self.request.match_info.get('chat_id'))

        request_chat = await GroupRoom.get(request_chat_id)

        if request_chat is None:
            return web.json_response(
                {'message': f'Chat with ID "{request_chat_id}" was not found'},
                status=404
            )

        if user.id != request_user_id:
            return web.json_response(
                {"message": "Deleting another user is forbidden"},
                status=403
            )

        user_group = await GroupMembership.query.where(
            and_(
                GroupMembership.user_id == request_user_id,
                GroupMembership.room_id == request_chat_id
            )
        ).gino.first()

        if user_group is None:
            message = f'User with ID "{request_user_id}" does not exist in chat'

            return web.json_response(
                {'message': message},
                status=404
            )

        await GroupMembership.delete.where(
            and_(
                GroupMembership.user_id == request_user_id,
                GroupMembership.room_id == request_chat_id
            )
        ).gino.status()

        last_user = await db \
            .select([db.func.count(GroupMembership.user_id)]) \
            .where(GroupMembership.room_id == request_chat_id) \
            .gino \
            .scalar()

        if last_user == 0:
            await GroupRoom.delete.where(
                GroupRoom.id == request_chat_id).gino.status()

        return web.json_response(status=204)


class ChatMessages(web.View, CorsViewMixin):
    @docs(
        tags=['Messages'],
        summary='Fetch all messages in a chat.',
        parameters=[{
            'in': 'header',
            'name': 'Authorization',
            'schema': {'type': 'string'},
            'required': 'true'
        }]
    )
    @response_schema(MessageResponseSchema(many=True))
    @token_and_active_required
    async def get(self):
        chat_id = self.request.match_info.get('chat_id')
        chat = await GroupRoom.get(int(chat_id))

        if not chat:
            return web.json_response(
                {'message': 'Chat not found.'}, status=404
            )
        user = self.request["user"]

        room_member = await GroupMembership.query.where(and_(
            GroupMembership.room_id == int(chat_id),
            GroupMembership.user_id == user.id)).gino.first()
        if not room_member:
            return web.json_response(
                {'message': "Getting messages is forbidden. "
                            "User is not in chat."}, status=403
            )

        query = GroupMessage.outerjoin(
            User, onclause=(GroupMessage.user_id == User.id)
        ).select().where(GroupMessage.room_id == int(chat_id)
                         ).order_by(GroupMessage.created_at)

        messages = await query.gino.load((GroupMessage, User.username)).all()

        return web.json_response(
            MessageResponseSchema().dump(
                [{
                    "id": message.id,
                    "text": message.text,
                    "created_at": message.created_at.isoformat(),
                    "username": username
                } for message, username in messages],
                many=True
            ).data)

    @docs(
        tags=['Messages'],
        summary='Create a new message.',
        parameters=[{
            'in': 'header',
            'name': 'Authorization',
            'schema': {'type': 'string'},
            'required': 'true'
        }]
    )
    @request_schema(MessageRequestSchema(strict=True))
    @token_and_active_required
    async def post(self):
        chat_id = self.request.match_info.get('chat_id')
        user = self.request["user"]

        room_member = await GroupMembership.query.where(and_(
            GroupMembership.room_id == int(chat_id),
            GroupMembership.user_id == user.id)).gino.first()
        if not room_member:
            return web.json_response(
                {'message': "Posting messages is forbidden. "
                            "User is not in chat."}, status=403
            )

        message = await GroupMessage.create(
            text=self.request["data"]["text"],
            room_id=int(chat_id),
            user_id=user.id
        )

        await GroupRoom.update.values(
            last_message_at=message.created_at,
            last_message_text=message.text
        ).where(GroupRoom.id == int(chat_id)).gino.status()

        room_members = await GroupMembership.query.where(
            GroupMembership.room_id == int(chat_id)
        ).gino.all()

        for room_member in room_members:
            member_ws: web.WebSocketResponse = self.request.app['websockets']\
                .get(room_member.user_id)

            if member_ws is None:
                continue

            await member_ws.send_json({
                'type': 'message',
                'data': {
                    'id': message.id,
                    'text': message.text,
                    'created_at': message.created_at.isoformat(),
                    'room_id': message.room_id,
                    'user_id': message.user_id,
                    'username': user.username
                }
            })

        return web.json_response(status=201)


class ChatMessageDetails(web.View, CorsViewMixin):
    @docs(tags=['Messages'],
          summary='Update a message.',
          parameters=[{
              'in': 'header',
              'name': 'Authorization',
              'schema': {'type': 'string'},
              'required': 'true'
          }]
          )
    @request_schema(MessageRequestSchema(strict=True))
    @token_and_active_required
    async def patch(self):
        data = await self.request.json()
        user = self.request['user']

        request_message_id = int(self.request.match_info.get('message_id'))
        request_chat_id = int(self.request.match_info.get('chat_id'))

        user_message = await GroupMessage.query.where(and_(
            GroupMessage.id == request_message_id,
            GroupMessage.room_id == request_chat_id)).gino.first()

        if not user_message:
            return web.json_response(
                {'message': "Message not found. Incorrect id"},
                status=404
            )

        if user.id != user_message.user_id:
            return web.json_response(
                {'message': "Changing another user's message is prohibited"},
                status=403
            )

        await user_message.update(
            text=data['text']
        ).apply()

        return web.json_response(status=204)

    @docs(tags=['Messages'],
          summary='Delete a message.',
          parameters=[{
              'in': 'header',
              'name': 'Authorization',
              'schema': {'type': 'string'},
              'required': 'true'
          }]
          )
    @token_and_active_required
    async def delete(self):
        user = self.request['user']

        request_message_id = int(self.request.match_info.get('message_id'))
        request_chat_id = int(self.request.match_info.get('chat_id'))

        user_message = await GroupMessage.query.where(and_(
            GroupMessage.id == request_message_id,
            GroupMessage.room_id == request_chat_id)).gino.first()

        if not user_message:
            return web.json_response(
                {'message': "Message not found. Incorrect id"},
                status=404
            )

        if user.id != user_message.user_id:
            return web.json_response(
                {'message': "Deleting another user's message is prohibited"},
                status=403
            )
        room_id = user_message.room_id

        await user_message.delete()

        last_message_at, last_message_text = await GroupMessage\
            .select('created_at', 'text')\
            .where(GroupMessage.room_id == room_id)\
            .order_by(GroupMessage.created_at.desc())\
            .gino\
            .first()

        await GroupRoom.update.values(
            last_message_at=last_message_at,
            last_message_text=last_message_text
        ).where(GroupRoom.id == room_id).gino.status()

        return web.json_response(status=204)
