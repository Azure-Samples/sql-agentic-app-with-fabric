CREATE TABLE [dbo].[accounts] (
    [id]             NVARCHAR (255)     NOT NULL,
    [user_id]        NVARCHAR (255)     NULL,
    [account_number] NVARCHAR (255)     NOT NULL,
    [account_type]   NVARCHAR (255)     NOT NULL,
    [balance]        DECIMAL (15, 2)    NOT NULL,
    [name]           NVARCHAR (255)     NOT NULL,
    [created_at]     DATETIMEOFFSET (7) DEFAULT (sysdatetimeoffset()) NULL,
    PRIMARY KEY CLUSTERED ([id] ASC),
    FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]),
    UNIQUE NONCLUSTERED ([account_number] ASC)
);


GO

