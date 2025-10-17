CREATE TABLE [dbo].[agent_definitions](
	[agent_id] [bigint] NOT NULL,
	[name] [nvarchar](255) NOT NULL,
	[version] [nchar](10) NOT NULL,
	[description] [nvarchar](max) NULL,
	[llm_config] [nvarchar](max) NOT NULL,
	[prompt_template] [nvarchar](max) NOT NULL,
 CONSTRAINT [PK__agent_de__2C05379EFE5AF58F] PRIMARY KEY CLUSTERED 
(
	[agent_id] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ__agent_de__72E12F1B351FAA8D] UNIQUE NONCLUSTERED 
(
	[name] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO

CREATE TABLE [dbo].[runs](
	[run_id] [bigint] NOT NULL,
	[thread_id] [bigint] NOT NULL,
	[input] [nvarchar](max) NOT NULL,
	[output] [nvarchar](max) NOT NULL,
	[start_time] [datetime] NOT NULL,
	[end_time] [datetime] NULL,
	[status] [nvarchar](10) NULL,
	[total_tokens] [int] NULL,
	[input_tokens] [int] NULL,
	[output_tokens] [int] NULL,
 CONSTRAINT [PK_runs] PRIMARY KEY CLUSTERED 
(
	[run_id] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO

CREATE TABLE [dbo].[threads](
	[thread_id] [bigint] IDENTITY(1,1) NOT NULL,
	[user_id] [bigint] NOT NULL,
	[created_time] [datetime] NOT NULL,
	[last_update_date] [datetime] NOT NULL,
	[agent_id] [bigint] NOT NULL,
 CONSTRAINT [PK_threads] PRIMARY KEY CLUSTERED 
(
	[thread_id] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO

CREATE TABLE [dbo].[tool_calls](
	[tool_call_id] [bigint] NOT NULL,
	[tool_id] [bigint] NOT NULL,
	[run_id] [bigint] NOT NULL,
	[start_time] [datetime] NULL,
	[end_time] [datetime] NULL,
	[status] [nvarchar](50) NULL,
	[attributes] [nvarchar](max) NULL,
	[input] [nvarchar](max) NULL,
	[output] [nvarchar](max) NULL,
 CONSTRAINT [PK_tool_calls] PRIMARY KEY CLUSTERED 
(
	[tool_call_id] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO

CREATE TABLE [dbo].[tool_definitions](
	[tool_id] [bigint] NOT NULL,
	[name] [nvarchar](255) NOT NULL,
	[description] [nvarchar](max) NULL,
	[input_schema] [nvarchar](max) NOT NULL,
	[version] [nvarchar](50) NULL,
	[is_active] [bit] NULL,
	[created_at] [datetime2](7) NULL,
	[updated_at] [datetime2](7) NULL,
PRIMARY KEY CLUSTERED 
(
	[tool_id] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
UNIQUE NONCLUSTERED 
(
	[name] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO

CREATE TABLE [dbo].[users](
	[user_id] [bigint] NOT NULL,
	[user_guid] [nvarchar](255) NOT NULL,
	[description] [nvarchar](500) NULL,
	[user_name] [nvarchar](500) NOT NULL,
 CONSTRAINT [PK_users] PRIMARY KEY CLUSTERED 
(
	[user_id] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[threads] ADD  CONSTRAINT [DF_threads_created_time]  DEFAULT (getdate()) FOR [created_time]
GO
ALTER TABLE [dbo].[threads] ADD  CONSTRAINT [DF_threads_last_update_date]  DEFAULT (getdate()) FOR [last_update_date]
GO
ALTER TABLE [dbo].[tool_definitions] ADD  DEFAULT ('1.0.0') FOR [version]
GO
ALTER TABLE [dbo].[tool_definitions] ADD  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [dbo].[tool_definitions] ADD  DEFAULT (getutcdate()) FOR [created_at]
GO
ALTER TABLE [dbo].[tool_definitions] ADD  DEFAULT (getutcdate()) FOR [updated_at]
GO
ALTER TABLE [dbo].[runs]  WITH CHECK ADD  CONSTRAINT [FK_runs_threads] FOREIGN KEY([thread_id])
REFERENCES [dbo].[threads] ([thread_id])
GO
ALTER TABLE [dbo].[runs] CHECK CONSTRAINT [FK_runs_threads]
GO
ALTER TABLE [dbo].[threads]  WITH CHECK ADD  CONSTRAINT [FK_threads_users] FOREIGN KEY([user_id])
REFERENCES [dbo].[users] ([user_id])
GO
ALTER TABLE [dbo].[threads] CHECK CONSTRAINT [FK_threads_users]
GO
ALTER TABLE [dbo].[tool_calls]  WITH CHECK ADD  CONSTRAINT [FK_tool_calls_run_steps] FOREIGN KEY([run_id])
REFERENCES [dbo].[run_steps] ([run_step_id])
GO
ALTER TABLE [dbo].[tool_calls] CHECK CONSTRAINT [FK_tool_calls_run_steps]
GO
ALTER TABLE [dbo].[tool_calls]  WITH CHECK ADD  CONSTRAINT [FK_tool_calls_runs] FOREIGN KEY([run_id])
REFERENCES [dbo].[runs] ([run_id])
GO
ALTER TABLE [dbo].[tool_calls] CHECK CONSTRAINT [FK_tool_calls_runs]
GO
ALTER TABLE [dbo].[tool_calls]  WITH CHECK ADD  CONSTRAINT [FK_tool_calls_tool_definitions] FOREIGN KEY([tool_id])
REFERENCES [dbo].[tool_definitions] ([tool_id])
GO
ALTER TABLE [dbo].[tool_calls] CHECK CONSTRAINT [FK_tool_calls_tool_definitions]
GO
