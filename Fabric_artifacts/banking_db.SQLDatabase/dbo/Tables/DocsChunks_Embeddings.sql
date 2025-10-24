CREATE TABLE [dbo].[DocsChunks_Embeddings] (
    [id]               UNIQUEIDENTIFIER NOT NULL,
    [custom_id]        VARCHAR (1000)   NULL,
    [content_metadata] JSON             NULL,
    [content]          NVARCHAR (MAX)   NOT NULL,
    [embeddings]       VECTOR (1536)    NOT NULL,
    PRIMARY KEY NONCLUSTERED ([id] ASC)
);


GO

CREATE UNIQUE NONCLUSTERED INDEX [idx_custom_id]
    ON [dbo].[DocsChunks_Embeddings]([custom_id] ASC);


GO

