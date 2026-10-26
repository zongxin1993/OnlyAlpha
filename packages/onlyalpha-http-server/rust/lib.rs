//! Native Product HTTP boundary.
pub mod configuration;
pub mod human_access;
pub mod ingress;
pub mod integration_types;
pub mod integrations;
pub mod node;

pub mod web_assets;

pub mod startup;

pub mod transport;
pub mod wire;

pub mod host;
pub mod routes;
pub mod workstation_startup;

mod host_commands;

mod host_observations;

mod host_storage;

mod host_acquisition;

mod host_websocket;
pub mod stream_wire;

mod host_probe;
mod host_temporary;
