use prost::Message;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: gateway-codegen DESCRIPTOR OUTPUT_DIRECTORY".into());
    }
    let descriptor = prost_types::FileDescriptorSet::decode(std::fs::read(&args[1])?.as_slice())?;
    prost_build::Config::new()
        .out_dir(&args[2])
        .compile_fds(descriptor)?;
    Ok(())
}
