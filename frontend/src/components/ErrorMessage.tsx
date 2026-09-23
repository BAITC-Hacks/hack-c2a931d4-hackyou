export function ErrorMessage({ error }: { error: Error | string | null }) {
  return error ? (
    <div className="error-message" role="alert">
      {typeof error === 'string' ? error : error.message}
    </div>
  ) : null;
}
