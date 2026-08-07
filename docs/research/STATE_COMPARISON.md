# Texas vs Washington

| Feature | Texas | Washington | Framework Impact |
|---------|--------|------------|------------------|
| Official Source | Legislature website | Legislature website | Shared |
| HTML | Yes | Yes | Shared |
| API | No | No | Shared |
| Title URL | No | Yes | Adapter-specific |
| Chapter URL | Yes | Yes | Shared |
| Section URL | Anchor inside chapter | Dedicated page | Adapter-specific |
| JavaScript | Required for chapter discovery | Not required | Adapter-specific |
| Search | Phrase search | Citation lookup | Future capability |
| BaseStateAdapter | Supported | Supported | No interface change |

The current BaseStateAdapter contract is sufficient for both Texas and Washington. Differences are confined to adapter implementation (URL construction, discovery, and retrieval strategy), supporting the architecture of a shared framework with state-specific adapters. This aligns with the research findings.