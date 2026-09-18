def calculate(api, inputs, parameters):
    return {"value": api.sub(inputs["close"], inputs["previous_close"])}
