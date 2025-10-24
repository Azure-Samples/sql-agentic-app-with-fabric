CREATE TABLE [dbo].[transactions] (
    [id]              NVARCHAR (255)     NOT NULL,
    [from_account_id] NVARCHAR (255)     NULL,
    [to_account_id]   NVARCHAR (255)     NULL,
    [amount]          DECIMAL (15, 2)    NOT NULL,
    [type]            NVARCHAR (255)     NOT NULL,
    [description]     NTEXT              NULL,
    [category]        NVARCHAR (255)     NULL,
    [status]          NVARCHAR (255)     NOT NULL,
    [created_at]      DATETIMEOFFSET (7) DEFAULT (sysdatetimeoffset()) NULL,
    PRIMARY KEY CLUSTERED ([id] ASC),
    FOREIGN KEY ([from_account_id]) REFERENCES [dbo].[accounts] ([id]),
    FOREIGN KEY ([to_account_id]) REFERENCES [dbo].[accounts] ([id])
);


GO

