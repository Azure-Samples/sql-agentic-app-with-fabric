CREATE TABLE [dbo].[tool_usage] (
    [tool_call_id] NVARCHAR (255) NOT NULL,
    [session_id]   NVARCHAR (255) NOT NULL,
    [trace_id]     NVARCHAR (255) NULL,
    [tool_id]      NVARCHAR (255) NOT NULL,
    [tool_name]    NVARCHAR (255) NOT NULL,
    [tool_input]   NVARCHAR (MAX) NOT NULL,
    [tool_output]  NVARCHAR (MAX) NULL,
    [tool_message] NVARCHAR (MAX) NULL,
    [status]       NVARCHAR (50)  NULL,
    [tokens_used]  INT            NULL,
    PRIMARY KEY CLUSTERED ([tool_call_id] ASC)
);


GO

