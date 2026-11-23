def calculate(api, inputs, parameters):
    previous = api.delay(inputs["close"], parameters["period"])
    return {"value": api.sub(api.div(inputs["close"], previous), api.decimal("1"))}
