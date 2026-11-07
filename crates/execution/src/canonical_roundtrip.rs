//! Compare the original JSON reader's meaning without constructing its full
//! temporary Value tree on the ordinary local-construction path. Bytes, hashes,
//! identity, parser syntax/depth limits and cold decoding remain unchanged.
use serde::{
    Deserialize, Deserializer,
    de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor},
};
use serde_json::Value;
use std::fmt;

#[cfg(test)]
std::thread_local! {
    static FULL_VALUE_READERS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

pub(crate) fn matches_value(bytes: &[u8], expected: &Value) -> bool {
    let mut reader = serde_json::Deserializer::from_slice(bytes);
    if Expected(expected).deserialize(&mut reader).is_ok() && reader.end().is_ok() {
        return true;
    }
    // In unusual representations (including reordered/duplicate keys), retain
    // precisely the original full Value reader and equality behavior. No new
    // reader error escapes the constructor's existing NONCANONICAL boundary.
    #[cfg(test)]
    FULL_VALUE_READERS.with(|count| count.set(count.get() + 1));
    serde_json::from_slice::<Value>(bytes).is_ok_and(|actual| actual == *expected)
}

struct Expected<'a>(&'a Value);
impl<'de> DeserializeSeed<'de> for Expected<'_> {
    type Value = ();

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<(), D::Error> {
        if let Value::Number(expected) = self.0 {
            // Number's mature visitor retains arbitrary_precision's exact
            // lexical normalization and private Number map handling. Never
            // compare through binary64 or an independent numeric parser.
            let actual = serde_json::Number::deserialize(deserializer)?;
            return if &actual == expected {
                Ok(())
            } else {
                Err(de::Error::custom("different JSON number"))
            };
        }
        if let Value::Object(expected) = self.0
            && expected.keys().any(|key| key.starts_with("$serde_json::"))
        {
            // Value's first-key Number/RawValue reinterpretation is private
            // dependency behavior. Delegate every such subtree to that exact
            // visitor, including its inner RawValue parser when enabled.
            #[cfg(test)]
            FULL_VALUE_READERS.with(|count| count.set(count.get() + 1));
            let actual = Value::deserialize(deserializer)?;
            return if &actual == self.0 {
                Ok(())
            } else {
                Err(de::Error::custom("different private JSON value"))
            };
        }
        deserializer.deserialize_any(ExpectedVisitor(self.0))
    }
}

struct ExpectedVisitor<'a>(&'a Value);
impl<'de> Visitor<'de> for ExpectedVisitor<'_> {
    type Value = ();

    fn expecting(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str("the exact original JSON value")
    }

    fn visit_unit<E: de::Error>(self) -> Result<(), E> {
        if self.0.is_null() {
            Ok(())
        } else {
            Err(E::custom("different JSON null"))
        }
    }

    fn visit_bool<E: de::Error>(self, actual: bool) -> Result<(), E> {
        if self.0.as_bool() == Some(actual) {
            Ok(())
        } else {
            Err(E::custom("different JSON bool"))
        }
    }

    fn visit_str<E: de::Error>(self, actual: &str) -> Result<(), E> {
        if self.0.as_str() == Some(actual) {
            Ok(())
        } else {
            Err(E::custom("different JSON string"))
        }
    }

    fn visit_borrowed_str<E: de::Error>(self, actual: &'de str) -> Result<(), E> {
        self.visit_str(actual)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut array: A) -> Result<(), A::Error> {
        let expected = self
            .0
            .as_array()
            .ok_or_else(|| de::Error::custom("different JSON type"))?;
        for value in expected {
            if array.next_element_seed(Expected(value))?.is_none() {
                return Err(de::Error::custom("short JSON array"));
            }
        }
        if array.next_element::<Value>()?.is_some() {
            return Err(de::Error::custom("long JSON array"));
        }
        Ok(())
    }

    fn visit_map<A: MapAccess<'de>>(self, mut object: A) -> Result<(), A::Error> {
        let expected = self
            .0
            .as_object()
            .ok_or_else(|| de::Error::custom("different JSON type"))?;
        // The local serializer emits each expected key once in this exact
        // order. A different order/duplicate falls back to the original Value
        // reader above, which retains its complete last-key-wins behavior.
        for (key, value) in expected {
            if object.next_key_seed(ExpectedKey(key))?.is_none() {
                return Err(de::Error::custom("short JSON object"));
            }
            object.next_value_seed(Expected(value))?;
        }
        if object.next_key::<String>()?.is_some() {
            return Err(de::Error::custom("long JSON object"));
        }
        Ok(())
    }
}

struct ExpectedKey<'a>(&'a str);
impl<'de> DeserializeSeed<'de> for ExpectedKey<'_> {
    type Value = ();

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<(), D::Error> {
        struct KeyVisitor<'a>(&'a str);
        impl Visitor<'_> for KeyVisitor<'_> {
            type Value = ();

            fn expecting(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
                output.write_str("the exact original JSON key")
            }

            fn visit_str<E: de::Error>(self, actual: &str) -> Result<(), E> {
                if self.0 == actual {
                    Ok(())
                } else {
                    Err(E::custom("different JSON key"))
                }
            }
        }
        deserializer.deserialize_str(KeyVisitor(self.0))
    }
}

#[cfg(test)]
#[path = "tests/canonical_roundtrip_tests.rs"]
mod tests;
