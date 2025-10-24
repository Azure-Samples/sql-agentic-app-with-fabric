CREATE TABLE [dbo].[users] (
    [id]         NVARCHAR (255)     NOT NULL,
    [name]       NVARCHAR (255)     NOT NULL,
    [email]      NVARCHAR (255)     NOT NULL,
    [created_at] DATETIMEOFFSET (7) DEFAULT (sysdatetimeoffset()) NULL,
    PRIMARY KEY CLUSTERED ([id] ASC),
    UNIQUE NONCLUSTERED ([email] ASC)
);


GO

