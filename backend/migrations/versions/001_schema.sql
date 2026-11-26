CREATE TABLE people (
	name VARCHAR NOT NULL, 
	team VARCHAR NOT NULL, 
	notes VARCHAR NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE projects (
	code VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	archived BOOLEAN NOT NULL, 
	payload JSON NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE project_members (
	project_id VARCHAR NOT NULL, 
	person_id VARCHAR NOT NULL, 
	PRIMARY KEY (project_id, person_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(person_id) REFERENCES people (id)
);

CREATE TABLE project_modules (
	project_id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	sort INTEGER NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, project_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE INDEX ix_project_modules_project_id ON project_modules (project_id);

CREATE TABLE project_scope_versions (
	id VARCHAR NOT NULL, 
	project_id VARCHAR NOT NULL, 
	number INTEGER NOT NULL, 
	effective_date VARCHAR NOT NULL, 
	created_at VARCHAR NOT NULL, 
	reason VARCHAR NOT NULL, 
	change_id VARCHAR, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, number), 
	UNIQUE (id, project_id), 
	FOREIGN KEY(change_id, project_id) REFERENCES requirement_changes (id, project_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE INDEX ix_project_scope_versions_project_id ON project_scope_versions (project_id);

CREATE TABLE tasks (
	name VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	plan_start VARCHAR NOT NULL, 
	plan_end VARCHAR NOT NULL, 
	owner_id VARCHAR NOT NULL, 
	module_id VARCHAR, 
	project_id VARCHAR NOT NULL, 
	code VARCHAR NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	payload JSON NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, project_id), 
	FOREIGN KEY(owner_id, project_id) REFERENCES project_members (person_id, project_id), 
	FOREIGN KEY(module_id, project_id) REFERENCES project_modules (id, project_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	UNIQUE (code)
);

CREATE INDEX ix_tasks_status ON tasks (status);

CREATE INDEX ix_tasks_plan_end ON tasks (plan_end);

CREATE INDEX ix_tasks_project_id ON tasks (project_id);

CREATE TABLE work_logs (
	work_date VARCHAR NOT NULL, 
	module_id VARCHAR NOT NULL, 
	owner_id VARCHAR NOT NULL, 
	task_id VARCHAR, 
	project_id VARCHAR NOT NULL, 
	code VARCHAR NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	payload JSON NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, project_id), 
	FOREIGN KEY(module_id, project_id) REFERENCES project_modules (id, project_id), 
	FOREIGN KEY(owner_id, project_id) REFERENCES project_members (person_id, project_id), 
	FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	UNIQUE (code)
);

CREATE INDEX ix_work_logs_work_date ON work_logs (work_date);

CREATE INDEX ix_work_logs_project_id ON work_logs (project_id);

CREATE TABLE requirement_changes (
	change_date VARCHAR NOT NULL, 
	module_id VARCHAR, 
	scope_id VARCHAR, 
	project_id VARCHAR NOT NULL, 
	code VARCHAR NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	payload JSON NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, project_id), 
	FOREIGN KEY(module_id, project_id) REFERENCES project_modules (id, project_id), 
	FOREIGN KEY(scope_id, project_id) REFERENCES project_scope_versions (id, project_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	UNIQUE (code)
);

CREATE INDEX ix_requirement_changes_project_id ON requirement_changes (project_id);

CREATE INDEX ix_requirement_changes_change_date ON requirement_changes (change_date);

CREATE TABLE risks (
	status VARCHAR NOT NULL, 
	raised_date VARCHAR NOT NULL, 
	task_id VARCHAR, 
	owner_id VARCHAR, 
	project_id VARCHAR NOT NULL, 
	code VARCHAR NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	payload JSON NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, project_id), 
	FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id), 
	FOREIGN KEY(owner_id, project_id) REFERENCES project_members (person_id, project_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	UNIQUE (code)
);

CREATE INDEX ix_risks_project_id ON risks (project_id);

CREATE INDEX ix_risks_raised_date ON risks (raised_date);

CREATE INDEX ix_risks_status ON risks (status);

CREATE TABLE participants (
	kind VARCHAR NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	person_id VARCHAR NOT NULL, 
	project_id VARCHAR NOT NULL, 
	PRIMARY KEY (kind, entity_id, person_id), 
	FOREIGN KEY(person_id, project_id) REFERENCES project_members (person_id, project_id)
);

CREATE TABLE change_task_links (
	change_id VARCHAR NOT NULL, 
	task_id VARCHAR NOT NULL, 
	project_id VARCHAR NOT NULL, 
	PRIMARY KEY (change_id, task_id), 
	FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id), 
	FOREIGN KEY(change_id, project_id) REFERENCES requirement_changes (id, project_id)
);

CREATE TABLE attachments (
	project_id VARCHAR, 
	name VARCHAR NOT NULL, 
	path VARCHAR NOT NULL, 
	size INTEGER NOT NULL, 
	mime VARCHAR NOT NULL, 
	sha256 VARCHAR NOT NULL, 
	description VARCHAR NOT NULL, 
	removed BOOLEAN NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, project_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	UNIQUE (path)
);

CREATE INDEX ix_attachments_project_id ON attachments (project_id);

CREATE TABLE attachment_links (
	attachment_id VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	project_id VARCHAR NOT NULL, 
	PRIMARY KEY (attachment_id, kind, entity_id), 
	FOREIGN KEY(attachment_id, project_id) REFERENCES attachments (id, project_id)
);

CREATE TABLE entity_revisions (
	id INTEGER NOT NULL, 
	project_id VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	effective_date VARCHAR NOT NULL, 
	recorded_at VARCHAR NOT NULL, 
	reason VARCHAR NOT NULL, 
	"before" JSON, 
	"after" JSON NOT NULL, 
	patch JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE INDEX ix_revision_history ON entity_revisions (project_id, kind, entity_id, effective_date);

CREATE TABLE idempotency_keys (
	"key" VARCHAR NOT NULL, 
	fingerprint VARCHAR NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	PRIMARY KEY ("key")
);

CREATE TABLE briefs (
	project_id VARCHAR NOT NULL, 
	start VARCHAR NOT NULL, 
	"end" VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE INDEX ix_briefs_project_id ON briefs (project_id);

CREATE TABLE brief_versions (
	id VARCHAR NOT NULL, 
	brief_id VARCHAR NOT NULL, 
	number INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	snapshot JSON NOT NULL, 
	content JSON NOT NULL, 
	model VARCHAR NOT NULL, 
	prompt_version VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (brief_id, number), 
	FOREIGN KEY(brief_id) REFERENCES briefs (id)
);

CREATE INDEX ix_brief_versions_brief_id ON brief_versions (brief_id);

CREATE TABLE generation_jobs (
	project_id VARCHAR NOT NULL, 
	brief_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	error VARCHAR NOT NULL, 
	retryable BOOLEAN NOT NULL, 
	attempts INTEGER NOT NULL, 
	model VARCHAR NOT NULL, 
	snapshot JSON NOT NULL, 
	result_id VARCHAR, 
	id VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(brief_id) REFERENCES briefs (id), 
	FOREIGN KEY(result_id) REFERENCES brief_versions (id)
);

CREATE INDEX ix_generation_jobs_project_id ON generation_jobs (project_id);