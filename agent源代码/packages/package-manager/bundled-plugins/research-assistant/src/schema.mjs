const Kind = Symbol.for('TypeBox.Kind'),
  OptionalKind = Symbol.for('TypeBox.Optional')

export const optional = (schema) => ({ ...schema, [OptionalKind]: 'Optional' })
export const string = (options = {}) => ({ [Kind]: 'String', type: 'string', ...options })
export const integer = (minimum, maximum) => ({ [Kind]: 'Integer', type: 'integer', minimum, maximum })
export const boolean = () => ({ [Kind]: 'Boolean', type: 'boolean' })
export const enumeration = (...values) => ({
  [Kind]: 'Union',
  anyOf: values.map((value) => ({ [Kind]: 'Literal', type: 'string', const: value })),
})
export const array = (items, options = {}) => ({ [Kind]: 'Array', type: 'array', items, ...options })
export const object = (properties) => {
  const required = Object.entries(properties)
    .filter(([, schema]) => schema[OptionalKind] !== 'Optional')
    .map(([name]) => name)
  return {
    [Kind]: 'Object',
    type: 'object',
    additionalProperties: false,
    ...(required.length ? { required } : {}),
    properties,
  }
}
