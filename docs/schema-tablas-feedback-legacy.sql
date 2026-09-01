-- Definicion de las tablas legacy de Feedback, dropeadas el 2026-09-01.
-- Las tres estaban vacias (0 filas) y sin uso: el modulo vigente usa
-- Pregunta / RespuestaFeedback / FeedbackConfig.
-- Se conserva el DDL por si alguna vez hiciera falta recrearlas.

-- ===== Respuesta =====
CREATE TABLE [Respuesta] (
    [id] int IDENTITY(1,1) NOT NULL,
    [feedbackId] int NOT NULL,
    [malo] int NOT NULL,
    [bueno] int NOT NULL,
    [excelente] int NOT NULL
);
ALTER TABLE [Respuesta] ADD CONSTRAINT [Respuesta_feedbackId_fkey] FOREIGN KEY ([feedbackId]) REFERENCES [Feedback]([id]);

-- ===== Feedback =====
CREATE TABLE [Feedback] (
    [id] int IDENTITY(1,1) NOT NULL,
    [evaluatorId] int NOT NULL,
    [evaluatedId] int NULL,
    [officeId] int NULL,
    [departmentId] int NOT NULL,
    [softSkillId] int NOT NULL,
    [activo] bit NOT NULL DEFAULT ((1)),
    [createdAt] datetime2 NOT NULL DEFAULT (getdate())
);
ALTER TABLE [Feedback] ADD CONSTRAINT [Feedback_evaluatorId_fkey] FOREIGN KEY ([evaluatorId]) REFERENCES [Employee]([id]);
ALTER TABLE [Feedback] ADD CONSTRAINT [Feedback_evaluatedId_fkey] FOREIGN KEY ([evaluatedId]) REFERENCES [Employee]([id]);
ALTER TABLE [Feedback] ADD CONSTRAINT [Feedback_departmentId_fkey] FOREIGN KEY ([departmentId]) REFERENCES [Department]([id]);
ALTER TABLE [Feedback] ADD CONSTRAINT [Feedback_officeId_fkey] FOREIGN KEY ([officeId]) REFERENCES [Office]([id]);
ALTER TABLE [Feedback] ADD CONSTRAINT [Feedback_softSkillId_fkey] FOREIGN KEY ([softSkillId]) REFERENCES [SoftSkill]([id]);

-- ===== FeedbackEvaluacion =====
CREATE TABLE [FeedbackEvaluacion] (
    [id] int IDENTITY(1,1) NOT NULL,
    [evaluatorEmployeeId] int NOT NULL,
    [evaluatedEmployeeId] int NOT NULL,
    [softSkillId] int NOT NULL,
    [cycleStart] datetime2 NOT NULL,
    [createdAt] datetime2 NOT NULL DEFAULT (getdate())
);
ALTER TABLE [FeedbackEvaluacion] ADD CONSTRAINT [FeedbackEvaluacion_evaluatorEmployeeId_fkey] FOREIGN KEY ([evaluatorEmployeeId]) REFERENCES [Employee]([id]);
ALTER TABLE [FeedbackEvaluacion] ADD CONSTRAINT [FeedbackEvaluacion_evaluatedEmployeeId_fkey] FOREIGN KEY ([evaluatedEmployeeId]) REFERENCES [Employee]([id]);
ALTER TABLE [FeedbackEvaluacion] ADD CONSTRAINT [FeedbackEvaluacion_softSkillId_fkey] FOREIGN KEY ([softSkillId]) REFERENCES [SoftSkill]([id]);
