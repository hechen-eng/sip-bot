# SIP Bot
This bot follows https://docs.livekit.io/agents/start/voice-ai-quickstart/.

To test outbound call, do
```
lk --project <project-name> dispatch create --new-room --agent-name <agent-name> --metadata '{"phone_number": "<your-personal-number>"}'
```

To create agent, do
```
lk agent create
```

After making some changes, do
```
lk agent deploy
```
