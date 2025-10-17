CREATE TABLE [dbo].[agent_definitions] (
    [agent_id]        NVARCHAR (255) NOT NULL,
    [name]            NVARCHAR (255) NOT NULL,
    [description]     NVARCHAR (MAX) NULL,
    [llm_config]      NVARCHAR (MAX) NOT NULL,
    [prompt_template] NVARCHAR (MAX) NOT NULL,
    PRIMARY KEY CLUSTERED ([agent_id] ASC),
    UNIQUE NONCLUSTERED ([name] ASC)
);


GO

