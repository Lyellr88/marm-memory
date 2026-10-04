// Types for the MARM Console frontend. These mirror the REST contract of the
// local MARM Console backend (FastAPI, run separately by the user on localhost).
// The frontend is a pure client against whatever base URL is configured in
// Settings.

export * from './types/overview';
export * from './types/memory';
export * from './types/runtime';
export * from './types/local-llm';
export * from './types/concepts';
export * from './types/projects';
export * from './types/code-context';
export * from './types/distill';
export * from './types/code-tools';
export * from './types/connections';
export * from './types/docker';
export * from './types/manual';
