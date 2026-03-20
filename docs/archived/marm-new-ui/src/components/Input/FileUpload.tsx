import React, { useRef, useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { 
  Upload, 
  File, 
  FileText, 
  Code, 
  Image,
  X,
  AlertCircle 
} from 'lucide-react';
import { cn } from '@/lib/utils';

const ACCEPTED_TYPES = [
  '.txt', '.js', '.html', '.css', '.json', '.md', 
  '.py', '.java', '.cpp', '.c', '.h', '.xml', 
  '.yaml', '.yml', '.ini', '.cfg', '.log'
];

const FILE_TYPE_ICONS = {
  text: <FileText className="w-4 h-4" />,
  code: <Code className="w-4 h-4" />,
  image: <Image className="w-4 h-4" />,
  default: <File className="w-4 h-4" />
};

interface FileUploadProps {
  onFileSelect: (files: File[]) => void;
  onClose: () => void;
  maxFiles?: number;
  maxSizeInMB?: number;
}

export const FileUpload: React.FC<FileUploadProps> = ({
  onFileSelect,
  onClose,
  maxFiles = 5,
  maxSizeInMB = 10
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getFileIcon = (fileName: string) => {
    const ext = fileName.toLowerCase();
    if (ext.includes('.png') || ext.includes('.jpg') || ext.includes('.jpeg') || ext.includes('.gif')) {
      return FILE_TYPE_ICONS.image;
    }
    if (ext.includes('.js') || ext.includes('.py') || ext.includes('.java') || ext.includes('.cpp')) {
      return FILE_TYPE_ICONS.code;
    }
    if (ext.includes('.txt') || ext.includes('.md') || ext.includes('.log')) {
      return FILE_TYPE_ICONS.text;
    }
    return FILE_TYPE_ICONS.default;
  };

  const validateFiles = (files: FileList): File[] => {
    const validFiles: File[] = [];
    const errors: string[] = [];

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      
      // Check file count
      if (validFiles.length >= maxFiles) {
        errors.push(`Maximum ${maxFiles} files allowed`);
        break;
      }

      // Check file size
      if (file.size > maxSizeInMB * 1024 * 1024) {
        errors.push(`${file.name} is too large (max ${maxSizeInMB}MB)`);
        continue;
      }

      // Check file type
      const extension = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!ACCEPTED_TYPES.includes(extension)) {
        errors.push(`${file.name} type not supported`);
        continue;
      }

      validFiles.push(file);
    }

    if (errors.length > 0) {
      setError(errors.join(', '));
      setTimeout(() => setError(null), 5000);
    } else {
      setError(null);
    }

    return validFiles;
  };

  const handleFiles = (files: FileList) => {
    const validFiles = validateFiles(files);
    if (validFiles.length > 0) {
      onFileSelect(validFiles);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      handleFiles(e.target.files);
    }
  };

  return (
    <Card className={cn(
      "absolute bottom-full right-0 mb-2 w-80",
      "bg-glass/95 backdrop-blur-md border-glass-border shadow-lg",
      "animate-scale-in z-50"
    )}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-glass-border">
        <div className="flex items-center gap-2">
          <Upload className="w-4 h-4 text-primary" />
          <span className="font-medium text-sm">Upload Files</span>
        </div>
        <Button
          onClick={onClose}
          size="sm"
          variant="ghost"
          className="w-6 h-6 p-0"
        >
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Upload Area */}
      <div className="p-4">
        <div
          className={cn(
            "border-2 border-dashed rounded-lg p-6 text-center transition-colors",
            dragActive 
              ? "border-primary bg-primary/5" 
              : "border-glass-border hover:border-primary/50"
          )}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          <Upload className={cn(
            "w-8 h-8 mx-auto mb-2",
            dragActive ? "text-primary" : "text-muted-foreground"
          )} />
          
          <p className="text-sm text-foreground mb-1">
            Drop files here or{' '}
            <Button
              variant="link"
              className="p-0 h-auto text-primary"
              onClick={() => fileInputRef.current?.click()}
            >
              browse
            </Button>
          </p>
          
          <p className="text-xs text-muted-foreground">
            Up to {maxFiles} files, {maxSizeInMB}MB each
          </p>
        </div>

        {/* Error Message */}
        {error && (
          <div className="mt-3 p-2 bg-destructive/10 text-destructive rounded-md flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span className="text-xs">{error}</span>
          </div>
        )}

        {/* Supported Types */}
        <div className="mt-4">
          <p className="text-xs font-medium text-muted-foreground mb-2">
            Supported file types:
          </p>
          <div className="flex flex-wrap gap-1">
            {ACCEPTED_TYPES.slice(0, 8).map(type => (
              <span
                key={type}
                className="text-xs bg-muted px-2 py-1 rounded"
              >
                {type}
              </span>
            ))}
            {ACCEPTED_TYPES.length > 8 && (
              <span className="text-xs text-muted-foreground px-2 py-1">
                +{ACCEPTED_TYPES.length - 8} more
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPTED_TYPES.join(',')}
        onChange={handleFileInput}
        className="hidden"
      />
    </Card>
  );
};