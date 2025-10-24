CREATE TABLE [dbo].[tool_definitions] (
    [tool_id]             NVARCHAR (255) NOT NULL,
    [name]                NVARCHAR (255) NOT NULL,
    [description]         NVARCHAR (MAX) NULL,
    [input_schema]        NVARCHAR (MAX) NOT NULL,
    [version]             NVARCHAR (50)  DEFAULT ('1.0.0') NULL,
    [is_active]           BIT            DEFAULT ((1)) NULL,
    [cost_per_call_cents] INT            DEFAULT ((0)) NULL,
    [created_at]          DATETIME2 (7)  DEFAULT (getutcdate()) NULL,
    [updated_at]          DATETIME2 (7)  DEFAULT (getutcdate()) NULL,
    PRIMARY KEY CLUSTERED ([tool_id] ASC),
    UNIQUE NONCLUSTERED ([name] ASC)
);


GO

