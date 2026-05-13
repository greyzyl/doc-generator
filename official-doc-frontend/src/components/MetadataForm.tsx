import type { TemplateField } from '../types/document';

interface MetadataFormProps {
  fields: TemplateField[];
  metadata: Record<string, string>;
  onChange: (key: string, value: string) => void;
}

export function MetadataForm({ fields, metadata, onChange }: MetadataFormProps) {
  return (
    <div className="form-list">
      {fields.map((field) => (
        <label key={field.fieldKey} className="field">
          <span className="field-label">
            {field.fieldName}
            {field.required && <b className="required">*</b>}
          </span>
          <FieldInput field={field} value={metadata[field.fieldKey] || ''} onChange={(value) => onChange(field.fieldKey, value)} />
        </label>
      ))}
    </div>
  );
}

interface FieldInputProps {
  field: TemplateField;
  value: string;
  onChange: (value: string) => void;
}

function FieldInput({ field, value, onChange }: FieldInputProps) {
  if (field.fieldType === 'textarea') {
    return (
      <textarea
        value={value}
        placeholder={field.placeholder || ''}
        rows={3}
        onChange={(event) => onChange(event.target.value)}
        className="input"
      />
    );
  }

  if (field.fieldType === 'select') {
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)} className="input">
        <option value="">请选择</option>
        {(field.options || []).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  return (
    <input
      type={field.fieldType === 'date' ? 'date' : 'text'}
      value={value}
      placeholder={field.placeholder || ''}
      maxLength={field.maxLength}
      onChange={(event) => onChange(event.target.value)}
      className="input"
    />
  );
}
