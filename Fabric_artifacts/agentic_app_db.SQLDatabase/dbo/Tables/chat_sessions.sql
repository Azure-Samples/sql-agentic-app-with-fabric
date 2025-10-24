CREATE TABLE [dbo].[chat_sessions] (
    [session_id]       NVARCHAR (255) NOT NULL,
    [user_id]          NVARCHAR (255) NOT NULL,
    [title]            NVARCHAR (500) NULL,
    [created_at]       DATETIME2 (7)  DEFAULT (getutcdate()) NULL,
    [updated_at]       DATETIME2 (7)  DEFAULT (getutcdate()) NULL,
    [duration_seconds] AS             (datediff(second,[created_at],[updated_at])),
    PRIMARY KEY CLUSTERED ([session_id] ASC)
);


GO

