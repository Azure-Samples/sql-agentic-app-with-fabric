CREATE TABLE [dbo].[chat_history] (
    [message_id]             NVARCHAR (255) NOT NULL,
    [session_id]             NVARCHAR (255) NOT NULL,
    [trace_id]               NVARCHAR (255) NOT NULL,
    [user_id]                NVARCHAR (255) NOT NULL,
    [agent_id]               NVARCHAR (255) NULL,
    [message_type]           NVARCHAR (50)  NOT NULL,
    [content]                NVARCHAR (MAX) NULL,
    [model_name]             NVARCHAR (255) NULL,
    [content_filter_results] NVARCHAR (MAX) DEFAULT ('{}') NULL,
    [total_tokens]           INT            NULL,
    [completion_tokens]      INT            NULL,
    [prompt_tokens]          INT            NULL,
    [finish_reason]          NVARCHAR (255) NULL,
    [response_time_ms]       INT            NULL,
    [trace_end]              DATETIME2 (7)  DEFAULT (getutcdate()) NULL,
    [tool_call_id]           NVARCHAR (255) NULL,
    [tool_name]              NVARCHAR (255) NULL,
    [tool_input]             NVARCHAR (MAX) NULL,
    [tool_output]            NVARCHAR (MAX) NULL,
    [tool_id]                NVARCHAR (255) NULL,
    PRIMARY KEY CLUSTERED ([message_id] ASC)
);


GO

