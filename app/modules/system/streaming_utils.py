from aiohttp import ClientResponse


async def stream_with_cleanup(response: ClientResponse):
    async with response:
        async for chunk in response.content:
            yield chunk
