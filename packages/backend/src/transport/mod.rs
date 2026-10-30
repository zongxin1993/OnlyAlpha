//! Transport responsibilities of the backend product.
pub mod endpoint;
pub mod host;
pub(crate) mod host_acquisition;
pub(crate) mod host_commands;
pub(crate) mod host_observations;
pub(crate) mod host_probe;
pub(crate) mod host_storage;
pub(crate) mod host_temporary;
pub(crate) mod host_websocket;
pub mod integration_types;
pub mod integrations;
pub mod routes;
pub mod stream_wire;
pub mod web_assets;
pub mod wire;

mod host_private_factors;

pub mod host_agent_browser;
pub mod host_factor_proposals;
pub mod host_factor_research;
pub(crate) mod host_factor_studies;
pub(crate) mod host_research_commands;
pub(crate) mod host_research_context;
pub(crate) mod host_research_inputs;
pub(crate) mod host_research_preparation;
pub mod research_wire;
