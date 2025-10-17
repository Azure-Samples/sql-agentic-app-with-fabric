CREATE TABLE [dbo].[PDF_RawChunks] (
    [id]         INT            IDENTITY (1, 1) NOT NULL,
    [chunk_text] NVARCHAR (MAX) NOT NULL,
    [source_pdf] NVARCHAR (512) NULL,
    [created_at] DATETIME2 (7)  DEFAULT (getdate()) NOT NULL,
    PRIMARY KEY CLUSTERED ([id] ASC)
);


GO

