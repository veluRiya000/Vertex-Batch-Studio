/** Private Node bridge credentials; never inherited by tool subprocesses. */
export const brokerCredentials=Object.freeze({
  url:process.env.VBS_HARNESS_BROKER_URL,
  token:process.env.VBS_HARNESS_BROKER_TOKEN,
});
delete process.env.VBS_HARNESS_BROKER_TOKEN;
